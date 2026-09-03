"""Pipeline runner (v5): the plan -> work -> review cycle.

Walks the phase graph (phase ids: plan, work, commit — the commit phase is
the REVIEWER):

    plan -> work -> review (commit)
        ^                |
        |                | verdict = "next_round"
        +----------------+  (a new cycle starts on every next_round)

There is NO task time limit T, NO global hard stop and NO cycle cap: the
agent cycles until the review verdict is "done" (or an unrecoverable
error). The container itself is killed at the task's own limit, and the
work phase keeps the deliverable file fresh on disk, so whatever exists at
kill time is what scores. The only bounds are the fixed per-operation ones
(plan 60s / work 120s / review 45s / bash 30s / llm wall 180s —
``budget.py``); explicit positive ``[phases.*].time`` values override the
phase caps (dev knob). The emergency phase (v4 terminal rescue) is UNUSED
in v5 — routing to it is hard-off; the class and its config section are
kept for compatibility.

Rules:
- A phase time cap (or a context-limit / persistent model error) is a
  NORMAL hand-off, never a retryable error: it triggers ONE extra toolless
  ``final_ask`` request on the same conversation ("write the deliverable
  now"), then hands off to the review phase (terminal).
- A phase ERROR (any other exception) in plan/work is retried up to the
  phase's ``max_retries`` (fresh run per attempt), then routes to the
  review phase. The review phase is never retried.
- The step guard (``[agent].max_steps`` when > 0, dev knob, off by
  default) bounds total phase runs; when exhausted the run stops with the
  status "timeout".
- Never crash: any unexpected failure is logged as ``agent_error`` and the
  process exits 0 (a crash scores 0 anyway; a partial deliverable may score
  1).

Log contract (the CLI dev engine parses a subset — ``usage`` and
``llm_tool_call`` — keep those fields stable; unknown events are ignored
by the CLI): agent_start, usage, llm_thinking, llm_tool_call,
llm_tool_result, run_usage, budget, phase, phase_done, phase_retry,
cycle, final_ask, commit (legacy, terminal-phase marker), agent_done,
agent_error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.providers.openai import OpenAIProvider

from shlepa_agent.budget import PLAN_CAP, REVIEW_CAP, WORK_CAP, regime
from shlepa_agent.config import AgentConfig, load_config
from shlepa_agent.log import (
    _configure_logging,
    _log_event,
    _log_stream_event,
)
from shlepa_agent.model import BudgetExceeded, TrackedModel
from shlepa_agent.outputs import PartialHandoff
from shlepa_agent.phases import get_phase
from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.state import extract_last_tools, save_state
from shlepa_agent.template import load_prompt, render_system
from shlepa_agent.tools import AgentDeps, get_tools

#: Hard cap for the one-shot final_ask request after a phase time-out.
FINAL_ASK_CAP_S = 30.0

_NULL_CTX = nullcontext()


def _telemetry_call(fn: str, *args: Any) -> None:
    """Best-effort call into shlepa_agent.telemetry (F4 root-span I/O).

    No-op unless SLEPA_OTEL_ENABLED=1; the telemetry module itself only
    exists in the dev install, so the import is lazy and any failure is
    swallowed: tracing must never break a run.
    """
    if os.environ.get("SLEPA_OTEL_ENABLED") != "1":
        return
    try:
        from shlepa_agent import telemetry

        getattr(telemetry, fn)(*args)
    except Exception:  # pragma: no cover - defensive, must never raise
        pass


def _final_ask_span_ctx(phase_id: str, prompt: str):
    """Context manager for the final_ask span; nullcontext when tracing is off."""
    if os.environ.get("SLEPA_OTEL_ENABLED") != "1":
        return _NULL_CTX
    try:
        from shlepa_agent import telemetry

        return telemetry.final_ask_span(phase_id, prompt)
    except Exception:  # pragma: no cover - defensive, must never raise
        return _NULL_CTX


def _phase_context(phase_id: str):
    """Per-phase execution context (F4); nullcontext when tracing is off."""
    if os.environ.get("SLEPA_OTEL_ENABLED") != "1":
        return _NULL_CTX
    try:
        from shlepa_agent import telemetry

        return telemetry.phase_context(phase_id)
    except Exception:  # pragma: no cover - defensive, must never raise
        return _NULL_CTX


def _stamp_final_ask(span: Any, *, ok: bool, text: str = "",
                     reason: str = "", error: str = "") -> None:
    """Stamp the outcome of a final_ask request on its span (None-safe)."""
    if span is None:
        return
    try:
        span.set_attribute("shlepa.ok", ok)
        if text:
            span.set_attribute("output.value", text[:4000])
        if reason:
            span.set_attribute("shlepa.reason", reason)
        if error:
            span.set_attribute("shlepa.error", error[:300])
    except Exception:  # pragma: no cover - defensive, must never raise
        pass

FINAL_ASK_MESSAGE = (
    "\u26a0\ufe0f HARD TIME LIMIT REACHED for this phase. Write the final "
    "deliverable NOW to the exact path in the exact format using only the "
    "information you already have. Do not call any tools and do not think "
    "any further: reply with one short line naming the deliverable path."
)


PARTIAL_HANDOFF_MESSAGE = (
    "\u23f1\ufe0f TIME LIMIT REACHED for this phase. Do not call any tools. "
    "Now emit the partial_handoff: summarize everything established so far — "
    "the deliverable objective (path/format/required values), key findings "
    "with their evidence locations, files already seen, working hypotheses, "
    "approaches already tried and rejected, and the single most valuable next "
    "action. A work phase starts fresh from this hand-off: be concrete and "
    "evidence-based, no fluff. Leave a field empty rather than guessing."
)


# ---------------------------------------------------------------------------
# Environment / model resolution (same contract as the contest entrypoint)
# ---------------------------------------------------------------------------


def _resolve_workdir() -> Path:
    # In the ACP image the agent cwd is /app; prefer it so task-relative paths work.
    app = Path("/app")
    if app.is_dir():
        return app
    raw = os.environ.get("LOCAL_AGENT_WORKDIR")
    if raw:
        return Path(raw).resolve()
    return Path.cwd().resolve()


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    raise ValueError(f"Missing required environment variable: {name}")


def _resolve_model_name() -> str:
    model_name = os.environ.get("LOCAL_AGENT_MODEL") or os.environ.get("OPENAI_MODEL")
    if model_name:
        return model_name
    raise ValueError(
        "Missing required model name: set LOCAL_AGENT_MODEL (preferred) or OPENAI_MODEL"
    )


def _is_handoff_error(exc: BaseException) -> bool:
    """True when a phase breach is a normal hand-off (status "timeout").

    Context-limit breaches and persistent model errors: the deliverable may
    already be partially usable, and the review phase gets the last word.
    These are NOT retryable — only unexpected errors are.
    """
    e: BaseException | None = exc
    seen: set[int] = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (BudgetExceeded, UsageLimitExceeded, ModelAPIError)):
            return True
        e = e.__cause__ or e.__context__
    return False


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def _system_prompt(agent_cfg: AgentConfig, phase: Phase, task: str) -> str:
    """Render the common system message for a phase (base + tools + task)."""
    tools = get_tools(agent_cfg, phase.tools(agent_cfg))
    return render_system(
        agent_cfg,
        phase.id,
        {
            "system": load_prompt("base.md"),
            "tools": "\n".join(f"- {tool.note}" for tool in tools),
            "task": task,
        },
    )


def build_phase_agent(
    model: TrackedModel,
    agent_cfg: AgentConfig,
    phase: Phase,
    task: str,
    instrument: bool = False,
) -> Agent:
    """Build a pydantic-ai agent for one phase (toolset from phase config).

    Phases with an ``output_type`` (plan, work) get the typed output tool;
    commit/emergency stay free text.
    """
    tools = get_tools(agent_cfg, phase.tools(agent_cfg))
    kwargs: dict[str, Any] = {}
    if phase.output_type is not None:
        kwargs["output_type"] = phase.output_type
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_system_prompt(agent_cfg, phase, task),
        **kwargs,
    )
    if instrument:
        agent.instrument = True
    for tool in tools:
        agent.tool(tool.run)
    return agent


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------


def _phase_cap(phase_id: str, limits: Any, cfg: AgentConfig) -> float:
    """Wall-clock cap for a phase run (fixed regime; dev-knob override).

    An explicit ``[phases.*].time`` value overrides the cap (dev knob).
    Otherwise the cap is the regime constant (``budget.py``); unknown ids
    (legacy emergency, never routed to in v5) get a fixed 60s window.
    """
    if limits.time is not None:
        return max(0.0, float(limits.time))
    if phase_id == "plan":
        return PLAN_CAP
    if phase_id == "work":
        return WORK_CAP
    if phase_id == "commit":  # review phase
        return REVIEW_CAP
    return 60.0


def _model_settings(cfg: AgentConfig) -> dict[str, Any]:
    """Per-request model settings.

    Temperature is NOT sent by default — the endpoint decides. It is sent
    only when ``agent.send_temp`` is enabled.
    """
    settings: dict[str, Any] = {}
    if cfg.agent.send_temp:
        settings["temperature"] = cfg.agent.temp
    return settings


async def _run_phase(
    state: RunState, phase: Phase, agent: Agent
) -> PhaseResult:
    """Run one phase under its wall-clock cap; returns its PhaseResult."""
    cfg = state.cfg
    model = state.model
    limits = phase.limits(cfg)
    cap = _phase_cap(phase.id, limits, cfg)
    model_settings: dict[str, Any] = _model_settings(cfg)
    if limits.reasoning_effort is not None:
        model_settings["openai_reasoning_effort"] = limits.reasoning_effort
    history = phase.history(state) or None
    if phase.terminal:
        _log_event(
            "commit",
            start=True,
            phase=phase.id,
            history_messages=len(history or []),
            time_cap_s=round(cap, 1),
            elapsed_s=round(model.elapsed(), 1),
        )
    output: Any = None
    try:
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                phase.prompt(state),
                deps=state.deps,
                model_settings=model_settings,
                # v5: no UsageLimits — token and request-count limits are
                # removed; the time caps (phase wall + per-request wall) are
                # the only bounds. Token usage stays logged for analysis.
                message_history=history,
            ) as events:
                async for event in events:
                    out = _log_stream_event(event)
                    if out is not None:
                        output = out
        model.log_pending_usage()
        if phase.output_type is not None:
            if not isinstance(output, BaseModel):
                # The run ended without a typed result (defensive; with an
                # output_type pydantic-ai retries until the limit is hit).
                _log_event("agent_error", error=f"phase {phase.id}: missing typed output")
                return PhaseResult(status="error", error="missing typed output")
            deliverable: str | None = getattr(output, "deliverable", None) or None
            return PhaseResult(
                status="done",
                summary=output.model_dump_json(),
                deliverable=deliverable,
                output=output,
            )
        return PhaseResult(status="done", summary=output or "")
    except (TimeoutError, asyncio.TimeoutError):
        model.log_pending_usage()
        _log_event(
            "budget",
            reason=f"{phase.id} time cap",
            detail=f"phase {phase.id} hit its {cap:.0f}s cap",
            elapsed_s=round(model.elapsed(), 1),
        )
        return PhaseResult(status="timeout", error=f"{phase.id} time cap reached")
    except Exception as e:
        model.log_pending_usage()
        if _is_handoff_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            return PhaseResult(status="timeout", error=str(e)[:300])
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return PhaseResult(status="error", error=f"{type(e).__name__}: {str(e)[:300]}")


async def _run_phase_with_retries(
    state: RunState, phase: Phase, instrument: bool
) -> PhaseResult:
    """Run a phase; retry ERROR results up to its max_retries.

    Timeout results (time cap / context-limit breach) are a normal hand-off
    (never retried), and the terminal phase is never retried. Each retry is
    a fresh run on the shared TrackedModel. The result is stored in
    state.results after every attempt, so a retry's prompt can see the
    previous attempt.
    """
    result = await _run_phase(
        state, phase, build_phase_agent(state.model, state.cfg, phase, state.task, instrument)
    )
    state.results[phase.id] = result
    max_retries = 0 if phase.terminal else state.cfg.phases[phase.id].max_retries
    attempts = 1
    while result.status == "error" and attempts <= max_retries:
        attempts += 1
        _log_event(
            "phase_retry",
            phase=phase.id,
            attempt=attempts,
            max_retries=max_retries,
            error=result.error or "",
        )
        result = await _run_phase(
            state, phase, build_phase_agent(state.model, state.cfg, phase, state.task, instrument)
        )
        state.results[phase.id] = result
    return result


async def _final_ask(state: RunState, phase: Phase) -> None:
    """One extra toolless request after a phase hard-timeout.

    Appends a single user message to the SAME conversation (byte-identical
    prompt prefix -> KV-cache reuse on the local server) and asks the model
    to write the deliverable right now, without tools. Its outcome does not
    change routing: plan/work -> review.
    """
    cfg = state.cfg
    model = state.model
    cap = FINAL_ASK_CAP_S
    history = trim_history(model.last_messages) or None
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_system_prompt(cfg, phase, state.task),
    )
    _log_event(
        "final_ask",
        phase=phase.id,
        start=True,
        mode="off",  # the v5 toolless message (no typed hand-off)
        cap_s=round(cap, 1),
        history_messages=len(history or []),
        elapsed_s=round(model.elapsed(), 1),
    )
    with _final_ask_span_ctx(phase.id, FINAL_ASK_MESSAGE) as span:
        text = ""
        try:
            async with asyncio.timeout(cap):
                async with agent.run_stream_events(
                    FINAL_ASK_MESSAGE,
                    deps=state.deps,
                    model_settings=_model_settings(cfg),
                    message_history=history,
                ) as events:
                    async for event in events:
                        out = _log_stream_event(event)
                        if out is not None:
                            text = str(out)
            model.log_pending_usage()
            _stamp_final_ask(span, ok=True, text=text)
            _log_event(
                "final_ask", phase=phase.id, ok=True, mode="off",
                elapsed_s=round(model.elapsed(), 1),
            )
        except (TimeoutError, asyncio.TimeoutError):
            model.log_pending_usage()
            _stamp_final_ask(span, ok=False, reason="time cap")
            _log_event(
                "final_ask",
                phase=phase.id,
                ok=False,
                mode="off",
                reason="time cap",
                elapsed_s=round(model.elapsed(), 1),
            )
        except Exception as e:
            model.log_pending_usage()
            _stamp_final_ask(span, ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
            _log_event(
                "final_ask",
                phase=phase.id,
                ok=False,
                mode="off",
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )


async def _plan_handoff(state: RunState, phase: Phase) -> None:
    """Plan-timeout hand-off (v6): one toolless final_ask, then store the
    hand-off payload in ``state.plan_handoff`` for the work prompt.

    With ``agent.handoff = "partial"`` (the v6 default) the final_ask is
    typed: it emits a ``PartialHandoff`` via the ``final_result`` output
    tool. Independently of the model's answer, the harness extracts the
    deterministic LAST_TOOLS tail of the plan conversation — key evidence
    survives even when the summary is weak. With ``handoff = "off"`` the
    v5 final_ask message is used and nothing is stored (A1 arm).
    """
    cfg = state.cfg
    model = state.model
    mode = (cfg.agent.handoff or "partial").lower()
    typed = mode != "off"
    cap = FINAL_ASK_CAP_S
    history = trim_history(model.last_messages) or None
    kwargs: dict[str, Any] = {}
    if typed:
        kwargs["output_type"] = PartialHandoff
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_system_prompt(cfg, phase, state.task),
        **kwargs,
    )
    message = PARTIAL_HANDOFF_MESSAGE if typed else FINAL_ASK_MESSAGE
    _log_event(
        "final_ask",
        phase=phase.id,
        start=True,
        mode=mode,
        cap_s=round(cap, 1),
        history_messages=len(history or []),
        elapsed_s=round(model.elapsed(), 1),
    )
    handoff_json: str | None = None
    with _final_ask_span_ctx(phase.id, message) as span:
        output: Any = None
        text = ""
        try:
            async with asyncio.timeout(cap):
                async with agent.run_stream_events(
                    message,
                    deps=state.deps,
                    model_settings=_model_settings(cfg),
                    message_history=history,
                ) as events:
                    async for event in events:
                        out = _log_stream_event(event)
                        if out is not None:
                            output = out
                            text = str(out)
            model.log_pending_usage()
            if typed:
                if isinstance(output, PartialHandoff):
                    handoff_json = output.model_dump_json()
                else:
                    _log_event(
                        "agent_error", error="plan handoff: missing typed output"
                    )
            _stamp_final_ask(span, ok=True, text=text or (handoff_json or ""))
            _log_event(
                "final_ask",
                phase=phase.id,
                ok=True,
                mode=mode,
                elapsed_s=round(model.elapsed(), 1),
            )
        except (TimeoutError, asyncio.TimeoutError):
            model.log_pending_usage()
            _stamp_final_ask(span, ok=False, reason="time cap")
            _log_event(
                "final_ask",
                phase=phase.id,
                ok=False,
                mode=mode,
                reason="time cap",
                elapsed_s=round(model.elapsed(), 1),
            )
        except Exception as e:
            model.log_pending_usage()
            _stamp_final_ask(span, ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
            _log_event(
                "final_ask",
                phase=phase.id,
                ok=False,
                mode=mode,
                error=f"{type(e).__name__}: {str(e)[:200]}",
            )
    if not typed:
        return  # "off": v5 behavior — no hand-off block
    state.plan_handoff = {
        "handoff": handoff_json,
        "last_tools": extract_last_tools(model.last_messages),
    }


# ---------------------------------------------------------------------------
# Pipeline walk
# ---------------------------------------------------------------------------


async def _pipeline(
    state: RunState,
    instrument: bool,
    phase_factory: Callable[[str], Phase],
    entry: str,
    max_steps: int | None,
) -> tuple[str, str]:
    """Walk the v5 pipeline (plan -> work -> review cycles); returns (status, output).

    status is the decisive outcome: "done" (the review verdict was done),
    "timeout" (a phase time cap / context-limit hand-off with no review
    verdict, or a step-guard stop), "error" (a phase failed after its
    retries). There is NO task time limit T, NO cycle cap and NO emergency
    routing: a "next_round" verdict ALWAYS starts a new plan/work cycle.
    """
    phase_id = entry
    steps = 0
    final_status = "done"
    output = ""

    while True:
        # Step guard (dev knob only; off by default).
        if (
            max_steps is not None
            and steps >= max_steps
            and phase_id != "commit"
        ):
            _log_event(
                "budget",
                reason="max_steps",
                detail=f"step guard {max_steps} exhausted",
            )
            return "timeout", output
        steps += 1
        phase = phase_factory(phase_id)
        _log_event(
            "phase",
            id=phase.id,
            start=True,
            cycle=state.cycles,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        start_t = state.model.elapsed()
        with _phase_context(phase.id):
            result = await _run_phase_with_retries(state, phase, instrument)
        _log_event(
            "phase_done",
            id=phase.id,
            status=result.status,
            duration_s=round(state.model.elapsed() - start_t, 1),
            elapsed_s=round(state.model.elapsed(), 1),
        )
        save_state(state)
        # Track the human-readable final output (terminal text wins).
        if result.summary:
            if phase.id == "work" and result.output is not None:
                output = result.output.summary or output
            elif phase.terminal:
                if isinstance(result.output, BaseModel):
                    # Typed terminal output (ReviewResult): report the
                    # deliverable path, or the notes line if any.
                    output = (
                        getattr(result.output, "notes", "")
                        or getattr(result.output, "artifact", "")
                        or ""
                    )
                else:
                    output = result.summary
            elif phase.id != "plan":
                output = result.summary
        if phase.terminal:
            # A review that itself failed (error after zero retries) or was
            # cut by its own time cap reports its own status — not "done".
            if result.status in ("timeout", "error"):
                return result.status, output
            # Review phase: "done" stops the run; "next_round" always starts
            # a new cycle (the container kill at the task's own limit is the
            # only external bound).
            verdict = getattr(result.output, "verdict", None)
            if verdict == "next_round":
                state.cycles += 1
                _log_event(
                    "cycle",
                    reason="next_round",
                    cycle=state.cycles,
                    elapsed_s=round(state.model.elapsed(), 1),
                )
                final_status = "done"
                phase_id = "plan"
                continue
            return (
                final_status if final_status in ("timeout", "error") else "done",
                output,
            )
        if phase.id == "plan" and result.status in ("timeout", "error"):
            # v6 routing invariant: every failed plan reaches WORK (a fresh
            # run), never the review shortcut. The dev knob
            # SHLEPA_ROUTE_PLAN_TIMEOUT=commit restores the v5 routes
            # (timeout: final_ask -> review; error -> review) for A0.
            route = (state.cfg.agent.route_plan_failure or "work").lower()
            if route == "commit":
                if result.status == "timeout":
                    with _phase_context(phase.id):
                        await _final_ask(state, phase)
                final_status = result.status
                phase_id = "commit"
            else:
                if result.status == "timeout":
                    with _phase_context(phase.id):
                        await _plan_handoff(state, phase)
                # WORK gets a note about the failed plan (error) or the
                # hand-off block (timeout); the review verdict is decisive
                # for the final status.
                final_status = "done"
                phase_id = "work"
            continue
        if result.status == "timeout":
            # WORK time cap / context-limit breach (unchanged from v5): one
            # toolless final_ask on the same conversation, then hand off to
            # the terminal review.
            with _phase_context(phase.id):
                await _final_ask(state, phase)
            final_status = "timeout"
            phase_id = "commit"
            continue
        if result.status == "error":
            final_status = "error"
            phase_id = "commit"
            continue
        if phase.id == "plan":
            # v6: the plan -> commit shortcut is gone — every done plan
            # flows to WORK (the w1-7 follow-up removes the now-unused
            # `decision` field from PlanResult).
            phase_id = "work"
            final_status = "done"
            continue
        # work -> review (there is no decision in WorkResult; the review's
        # verdict decides done vs. a new cycle).
        phase_id = "commit"
        final_status = "done"
        continue


async def run_prompt(
    prompt: str,
    instrument: bool = False,
    agent_cfg: AgentConfig | None = None,
    phase_factory: Callable[[str], Phase] | None = None,
) -> str:
    """Run the full phase pipeline for one task prompt; returns final output.

    Never raises: any unexpected failure is logged as agent_error (+ a final
    agent_done with status "error") and "" is returned, so the process exits
    0.
    """
    _configure_logging()
    _telemetry_call("mark_input", prompt)  # F4: root-span input.value
    cfg = agent_cfg or load_config()
    model: TrackedModel | None = None
    try:
        # v5 pipeline values: no time horizon — the entry is always "plan"
        # (a ``[agent].entry`` override is a dev knob) and there is NO cycle
        # cap: "next_round" always starts a new cycle.
        entry = cfg.agent.entry or "plan"
        max_steps: int | None = cfg.agent.max_steps or None  # dev knob, off by default

        workdir = _resolve_workdir()
        model = TrackedModel(
            _resolve_model_name(),
            OpenAIProvider(
                base_url=_required_env("OPENAI_BASE_URL"),
                api_key=_required_env("OPENAI_API_KEY"),
            ),
            cfg,
        )
        state = RunState(
            task=prompt,
            deps=AgentDeps(workdir=workdir, cfg=cfg, clock=model.elapsed),
            model=model,
        )
        _log_event(
            "agent_start",
            model=_resolve_model_name(),
            base_url=_required_env("OPENAI_BASE_URL"),
            workdir=str(workdir),
            prompt=prompt,
            # reported only when it is actually sent to the endpoint (#65)
            **({"temp": cfg.agent.temp} if cfg.agent.send_temp else {}),
            entry=entry,
            emergency=cfg.agent.emergency,
            # Fixed regime (additive, CLI ignores unknown fields):
            plan_cap=round(PLAN_CAP, 1),
            work_cap=round(WORK_CAP, 1),
            review_cap=round(REVIEW_CAP, 1),
            bash_cap=round(regime()["bash"], 1),
            llm_wall=round(regime()["llm_wall"], 1),
            max_steps=max_steps,
        )
        _log_event(
            "budget",
            reason="regime",
            detail=str(regime()),
        )
        save_state(state)
        factory = phase_factory or get_phase
        status, output = await _pipeline(
            state, instrument, factory, entry, max_steps
        )
        model.log_pending_usage()
        _log_event(
            "agent_done",
            status=status,
            elapsed_s=round(model.elapsed(), 1),
            output=output,
        )
        _telemetry_call("mark_outcome", status, output)  # F4: root-span I/O
        return output
    except Exception as e:
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        elapsed = round(model.elapsed(), 1) if model is not None else 0.0
        _log_event("agent_done", status="error", elapsed_s=elapsed, output="")
        _telemetry_call("mark_outcome", "error", "")  # F4: root-span status
        return ""


def main(instrument: bool = False) -> None:
    parser = argparse.ArgumentParser(description="Run local non-interactive coding agent")
    parser.add_argument("prompt", nargs="+", help="Prompt for the agent")
    args = parser.parse_args()
    prompt = " ".join(args.prompt)
    try:
        output = asyncio.run(run_prompt(prompt, instrument=instrument))
    except Exception as e:
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        print(f"agent failed: {type(e).__name__}: {e}")
        sys.exit(0)
    if output:
        print(output)


if __name__ == "__main__":
    main()
