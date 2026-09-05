"""Pipeline runner (v6-rewrite): the HARD cycle regime.

Exactly ``[agent].max_cycles`` (env ``SHLEPA_MAX_CYCLES``, default 2) plan
-> work cycles, with a REVIEW RELAY after every cycle except the last:

    plan_1 -> work_1 -> review_1 (relay) -> plan_2 -> work_2 -> exit

The relay is a toolless distillation of the just-finished WORK transcript:
it emits the typed ``ReviewResult`` (summary / done / problems /
hints_next) that the next cycle's PLAN (together with the previous work
result) and WORK (the relay alone) receive. It never judges, never routes
and never decides the exit — the run always ends right after the last
WORK, and the final status is decided by that last WORK alone (a PLAN
timeout or error does not change the outcome once its WORK ran).

There is NO task time limit T and NO soft cycle cap: the container is
killed at the task's own limit, and the work phase keeps the deliverable
file fresh on disk, so whatever exists at kill time is what scores (the
mechanical ``deliverable_check`` gate runs after every work; the w2-9
best-at-exit snapshot is DISABLED, functions kept on disk). The only
bounds are the fixed per-operation ones (plan 30s / work 120s / review
45s / bash 30s / llm wall 180s — ``budget.py``; plus the 15 s
finalization reserve); explicit positive ``[phases.*].time`` values
override the phase caps (dev knob).

Disabled phases (files, prompts and config sections stay on disk for a
later re-enable; the runner never routes to them): commit (the v6
verifier), repair, salvage and emergency. Their routing logic is kept
behind the ``[tool_policy].disabled`` list in ``config.toml``.

Rules:
- A phase time cap (or a context-limit / persistent model error) in PLAN
  is a NORMAL hand-off, never a retryable error: a typed partial handoff
  (``PartialHandoff``) is built for the WORK's LAST_TOOLS block and the
  WORK runs anyway. A PLAN error (any other exception) is retried up to
  the phase's ``max_retries`` (fresh run per attempt), then the same
  hand-off applies.
- A WORK time cap triggers ONE extra toolless ``final_ask`` request on
  the same conversation ("write the deliverable now"); then the run
  either exits (last cycle) or hands off to the relay (cycles before
  the last). A WORK error is retried up to ``max_retries``, then the
  same path.
- The relay is never retried; its timeout/error is logged as
  ``review_fallback`` and the next cycle proceeds without it.
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
cycle, final_ask, deliverable_check, endpoint_error, endpoint_stalled,
endpoint_finalized, test_guard, test_tamper, agent_done, agent_error.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.providers.openai import OpenAIProvider

from shlepa_agent.budget import PLAN_CAP, REVIEW_CAP, WORK_CAP, regime
from shlepa_agent.config import AgentConfig, load_config
from shlepa_agent.deliverable_check import ArtifactSpec, check_deliverable
from shlepa_agent.log import (
    _configure_logging,
    _log_event,
    _log_stream_event,
)
from shlepa_agent.model import BudgetExceeded, TrackedModel
from shlepa_agent.outputs import PartialHandoff, ReviewResult
from shlepa_agent.phases import get_phase
from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.state import extract_last_tools, save_state
from shlepa_agent.test_guard import bootstrap_test_hashes, check_test_hashes
from shlepa_agent.template import load_prompt, render_system
from shlepa_agent.tools import AgentDeps, get_tools
from shlepa_agent.tools.base import PhaseWindow, RepairScope

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
    cycle: int = 1,
) -> Agent:
    """Build a pydantic-ai agent for one phase (toolset from the tool policy).

    Phases with an ``output_type`` (plan, work, review) get the typed output
    tool; disabled free-text phases (commit, emergency) would stay free text.
    """
    tools = get_tools(agent_cfg, phase.tools(agent_cfg, cycle))
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
    if phase_id in ("commit", "review"):  # relay (v6-rewrite) / verifier (disabled)
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


def _budget_header(
    phase_id: str, elapsed_total: float, cap: float | None, phase_elapsed: float, prompt: str
) -> str:
    """w3-1: prepend ``[phase=<id> elapsed=<s> remaining=<s>]`` to a request.

    Known quantities only: the phase's own wall-clock cap and the
    monotonic clock — never a guessed per-task deadline or token budget.
    """
    if cap is None:
        return prompt
    remaining = max(0.0, cap - phase_elapsed)
    return (
        f"[phase={phase_id} elapsed={elapsed_total:.0f}s "
        f"remaining={remaining:.0f}s]\n\n{prompt}"
    )


async def _run_phase(
    state: RunState, phase: Phase, agent: Agent
) -> PhaseResult:
    """Run one phase under its wall-clock cap; returns its PhaseResult."""
    cfg = state.cfg
    model = state.model
    limits = phase.limits(cfg)
    cap = _phase_cap(phase.id, limits, cfg)
    t0 = time.monotonic()
    # w3-2: expose the phase window to the tools so the finalization
    # reserve can disable exploratory calls (bash/search/recon) in the
    # last R seconds of the cap.
    state.deps = replace(state.deps, phase_window=PhaseWindow(phase.id, cap, t0))
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
        prompt = _budget_header(
            phase.id, model.elapsed(), cap, time.monotonic() - t0, phase.prompt(state)
        )
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                prompt,
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
    state: RunState, phase: Phase, instrument: bool, cycle: int = 1
) -> PhaseResult:
    """Run a phase; retry ERROR results up to its max_retries.

    Timeout results (time cap / context-limit breach) are a normal hand-off
    (never retried). Each retry is a fresh run on the shared TrackedModel.
    The result is stored in state.results after every attempt, so a retry's
    prompt can see the previous attempt. ``cycle`` selects the per-iteration
    tool policy (``<phase>_c<N>`` overrides, v6-rewrite).
    """
    result = await _run_phase(
        state, phase, build_phase_agent(
            state.model, state.cfg, phase, state.task, instrument, cycle=cycle
        )
    )
    state.results[phase.id] = result
    max_retries = 0 if phase.terminal else state.cfg.phases[phase.id].max_retries
    attempts = 1
    while result.status == "error" and attempts <= max_retries:
        # w3-5: never issue another request to a stalled endpoint.
        if _model_endpoint_stalled(state):
            break
        attempts += 1
        _log_event(
            "phase_retry",
            phase=phase.id,
            attempt=attempts,
            max_retries=max_retries,
            error=result.error or "",
        )
        result = await _run_phase(
            state, phase, build_phase_agent(
                state.model, state.cfg, phase, state.task, instrument, cycle=cycle
            )
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
    ask = _budget_header(phase.id, model.elapsed(), cap, 0.0, FINAL_ASK_MESSAGE)
    with _final_ask_span_ctx(phase.id, FINAL_ASK_MESSAGE) as span:
        text = ""
        try:
            async with asyncio.timeout(cap):
                async with agent.run_stream_events(
                    ask,
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
    """Plan-timeout hand-off (v6-rewrite, the only plan-failure route):
    one toolless TYPED final_ask, then store the hand-off payload in
    ``state.plan_handoff`` for the work prompt.

    The final_ask emits a ``PartialHandoff`` via the ``final_result`` output
    tool. Independently of the model's answer, the harness extracts the
    deterministic LAST_TOOLS tail of the plan conversation — key evidence
    survives even when the summary is weak. (The legacy A0/A1 knob
    SHLEPA_HANDOFF is removed; the typed hand-off is the single behavior.)
    """
    cfg = state.cfg
    model = state.model
    mode = "partial"
    cap = FINAL_ASK_CAP_S
    history = trim_history(model.last_messages) or None
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_system_prompt(cfg, phase, state.task),
        output_type=PartialHandoff,
    )
    message = PARTIAL_HANDOFF_MESSAGE
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
            if isinstance(output, PartialHandoff):
                handoff_json = output.model_dump_json()
            else:
                _log_event("agent_error", error="plan handoff: missing typed output")
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
    state.plan_handoff = {
        "handoff": handoff_json,
        "last_tools": extract_last_tools(model.last_messages),
    }


# ---------------------------------------------------------------------------
# Post-work deliverable gate (v6, w2-3)
# ---------------------------------------------------------------------------


def _salvage_enabled() -> bool:
    """Kill-switch for the salvage route: SHLEPA_SALVAGE=0|false|off disables."""
    return os.environ.get("SHLEPA_SALVAGE", "1").strip().lower() not in (
        "0",
        "false",
        "off",
    )


def _resolve_deliverable_spec(state: RunState) -> dict[str, Any] | None:
    """Best-known deliverable spec after WORK.

    The plan's ``artifact_spec`` wins; ``WorkResult.deliverable`` fills a
    missing path (and is the only source when the plan produced no typed
    output). Returns None when no path is known (the gate then stays off).
    """
    spec: ArtifactSpec | None = None
    plan = state.results.get("plan")
    if plan is not None and plan.output is not None:
        out = plan.output
        raw = getattr(out, "artifact_spec", None)
        if raw is None and isinstance(out, dict):
            raw = out.get("artifact_spec")
        spec = ArtifactSpec.from_any(raw)
    work = state.results.get("work")
    work_path = ""
    if work is not None and work.output is not None:
        out = work.output
        work_path = getattr(out, "deliverable", "") or ""
        if not work_path and isinstance(out, dict):
            work_path = out.get("deliverable") or ""
    if work_path:
        if spec is None:
            spec = ArtifactSpec(path=work_path)
        elif not spec.path:
            spec = ArtifactSpec(
                kind=spec.kind,
                path=work_path,
                format=spec.format,
                keys=spec.keys,
                expected_content=spec.expected_content,
            )
    if spec is None or not spec.path:
        return None
    return {
        "kind": spec.kind,
        "path": spec.path,
        "format": spec.format,
        "keys": list(spec.keys),
        "expected_content": spec.expected_content,
    }


def _post_work_check(state: RunState) -> None:
    """Resolve the deliverable spec after WORK and run the mechanical check.

    Stores both in the run state (``deliverable_spec`` / ``deliverable_check``)
    for the salvage gate and, eventually, the REVIEW context packet. Never
    raises: a check failure must not break the run.
    """
    try:
        spec = _resolve_deliverable_spec(state)
        state.deliverable_spec = spec
        if spec is None:
            state.deliverable_check = None
            return
        state.deliverable_check = check_deliverable(
            state.deps.workdir, spec
        ).to_dict()
        # v6-rewrite: best-at-exit snapshots are DISABLED (single source of
        # truth is the file after the last work). _maybe_snapshot_best /
        # _restore_best_on_exit stay on disk for a later re-enable.
        # _maybe_snapshot_best(state)
    except Exception as e:  # pragma: no cover - defensive
        _log_event("agent_error", error=f"post-work check: {type(e).__name__}: {str(e)[:200]}")
        state.deliverable_check = None


def _maybe_snapshot_best(state: RunState) -> None:
    """w2-9: remember the last check-passing deliverable.

    Snapshot (path + sha256 + content) so a later round that leaves a
    broken file cannot regress a passing one. Never raises.
    """
    try:
        check = state.deliverable_check
        spec = state.deliverable_spec
        if not (check and check.get("valid")) or spec is None:
            return
        p = Path(spec["path"])
        if not p.is_absolute():
            p = state.deps.workdir / p
        content = p.read_text(encoding="utf-8", errors="replace")
        state.best_snapshot = {
            "path": spec["path"],
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        }
    except Exception as e:  # pragma: no cover - defensive
        _log_event("agent_error", error=f"best snapshot: {type(e).__name__}: {str(e)[:200]}")


def _verify_test_hashes(state: RunState) -> None:
    """w3-6: at exit, re-hash the in-environment test files; a change
    marks the run's own test results invalid (event + state flag).
    Never raises.
    """
    try:
        if not state.test_hashes:
            return
        changed = check_test_hashes(state.deps.workdir, state.test_hashes)
        if changed:
            state.test_tampered = True
            _log_event(
                "test_tamper", count=len(changed), files=changed[:20]
            )
    except Exception as e:  # pragma: no cover - defensive
        _log_event("agent_error", error=f"test guard: {type(e).__name__}: {str(e)[:200]}")


def _restore_best_on_exit(state: RunState) -> None:
    """w2-9: at exit, if the current deliverable fails the check but a
    passing snapshot exists and the file changed, restore the snapshot —
    a killed round-2 overwrite cannot regress round-1. Never raises.
    """
    try:
        snap = state.best_snapshot
        if snap is None:
            return
        _post_work_check(state)  # refresh the check against the file on disk
        check = state.deliverable_check
        if check and check.get("valid"):
            return
        p = Path(snap["path"])
        if not p.is_absolute():
            p = state.deps.workdir / p
        current = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        if current is not None and \
                hashlib.sha256(current.encode("utf-8")).hexdigest() == snap["sha256"]:
            return  # already the best file
        tmp = p.with_name(p.name + ".v6restore")
        tmp.write_text(snap["content"], encoding="utf-8")
        os.replace(tmp, p)
        _post_work_check(state)
        _log_event(
            "artifact_restored",
            path=snap["path"],
            sha256=snap["sha256"][:12],
            check=state.deliverable_check,
        )
    except Exception as e:  # pragma: no cover - defensive
        _log_event("agent_error", error=f"restore best: {type(e).__name__}: {str(e)[:200]}")


def _endpoint_finalize(state: RunState) -> str:
    """w3-5: reactive endpoint shutdown.

    Consecutive terminal endpoint failures (429/402/5xx) are the only
    observable proxy for the invisible external token cap: stop issuing
    new LLM requests, persist the best deliverable snapshot (or the file
    on disk when no snapshot exists), tag the root span
    ``shlepa.termination_reason=endpoint_finalized`` and end the run
    normally (the process exits 0).
    """
    model = state.model
    _log_event(
        "endpoint_finalized",
        reason="consecutive terminal endpoint failures",
        failures=model.endpoint_failure_count,
    )
    _restore_best_on_exit(state)
    _telemetry_call("mark_termination", "endpoint_finalized")
    return "done"


def _model_endpoint_stalled(state: RunState) -> bool:
    """w3-5: has the model seen >= endpoint_fail_limit consecutive
    terminal endpoint failures? Best-effort: False when the model does
    not expose the counter (dev wrappers / stubs)."""
    try:
        return bool(state.model.endpoint_stalled)
    except Exception:  # pragma: no cover - defensive
        return False


def _commit_fallback_hints(state: RunState, check: dict | None) -> None:
    """w2-6: on a deterministic VERIFY fallback, make sure the next plan
    sees the recorded failed checks as hints (the plan prompt renders
    ``state.results['commit'].output.hints``)."""
    prev = state.results.get("commit")
    own = None
    if prev is not None and prev.output is not None:
        own = getattr(prev.output, "hints", None) or []
    hints = list(own or [])
    if check is not None:
        hints.append(
            "mechanical deliverable check (harness) FAILED: "
            + json.dumps(check)
            + " — fix the named failures"
        )
    status = prev.status if prev is not None else "timeout"
    state.results["commit"] = PhaseResult(
        status=status,
        summary="VERIFY ended without a verdict (harness fallback)",
        output=ReviewResult(
            status="partial",
            verdict="next_round",
            artifact=(state.deliverable_spec or {}).get("path", ""),
            checks=[],
            hints=hints,
        ),
    )


def _salvage_needed(state: RunState) -> bool:
    """Salvage fires only on a missing/empty deliverable with a known path."""
    check = state.deliverable_check
    if not check or not state.deliverable_spec:
        return False
    if check.get("exists") and check.get("non_empty"):
        return False
    if "salvage" not in state.cfg.phases:
        return False  # not configured (e.g. dev test configs)
    return _salvage_enabled()


def _persist_salvage_body(state: RunState) -> None:
    """Persist the salvage final_result.body if the file is still absent.

    Atomic (tmp file in the same directory + os.replace). A file the model
    itself wrote wins — the body is only the fallback.
    """
    spec = state.deliverable_spec
    result = state.results.get("salvage")
    if not spec or result is None or result.status != "done" or result.output is None:
        return
    out = result.output
    body = getattr(out, "body", "") or ""
    if not body and isinstance(out, dict):
        body = out.get("body") or ""
    if not body:
        return
    path = Path(spec["path"])
    if not path.is_absolute():
        path = state.deps.workdir / path
    if path.is_file() and path.stat().st_size > 0:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".salvage-tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, path)
        _log_event("salvage_persist", path=str(path), chars=len(body))
    except OSError as e:
        _log_event("agent_error", error=f"salvage persist: {e}")


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
    """Walk the v6-rewrite pipeline: a HARD cycle loop; returns (status, output).

    Regime: exactly ``agent.max_cycles`` (env: SHLEPA_MAX_CYCLES, default 2)
    plan -> work cycles. After every cycle EXCEPT the last, a REVIEW relay
    (toolless distillation on the resumed work transcript, typed
    ReviewResult) hands the state over to the next cycle: PLAN of cycle
    i >= 2 receives the previous work result plus the previous relay, and
    WORK of cycle i >= 2 additionally receives the previous relay.

    The relay NEVER routes and NEVER decides: the run ends exactly after
    WORK_N (status = the last work's outcome; "done" / "timeout" / "error"),
    then the mechanical exit gate (deliverable check + test hashes) runs in
    run_prompt. The commit/repair/salvage/emergency phases exist on disk
    but are never routed to (disabled, kept for re-enable).
    """
    n_cycles = max(1, int(state.cfg.agent.max_cycles or 2))
    steps = 0
    final_status = "done"
    output = ""
    cycle = 1  # 1-based; state.cycles (0-based replan count) stays in sync

    while True:
        # Step guard (dev knob only; off by default). It stops between
        # cycles, never in the middle of the last one.
        if max_steps is not None and steps >= max_steps and cycle < n_cycles:
            _log_event(
                "budget",
                reason="max_steps",
                detail=f"step guard {max_steps} exhausted",
            )
            return "timeout", output
        steps += 1
        state.cycles = cycle - 1

        # ---- PLAN_c (fresh context) --------------------------------------
        # cycle 1: the instruction only; cycle >= 2: the instruction plus
        # the previous work result and the previous review relay.
        phase = phase_factory("plan")
        _log_event(
            "phase",
            id=phase.id,
            start=True,
            cycle=state.cycles,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        start_t = state.model.elapsed()
        with _phase_context(phase.id):
            result = await _run_phase_with_retries(
                state, phase, instrument, cycle=cycle
            )
        _log_event(
            "phase_done",
            id=phase.id,
            status=result.status,
            duration_s=round(state.model.elapsed() - start_t, 1),
            elapsed_s=round(state.model.elapsed(), 1),
        )
        if _model_endpoint_stalled(state):
            _log_event(
                "endpoint_stalled",
                phase=phase.id,
                failures=state.model.endpoint_failure_count,
            )
            return "done", _endpoint_finalize(state)
        save_state(state)
        # v6 routing invariant: WORK is never skipped. A plan timeout
        # becomes a typed PartialHandoff for the work prompt; a plan error
        # becomes a "no plan — execute directly" note. The work outcome
        # decides the run's status, not the plan's.
        if result.status == "timeout":
            with _phase_context(phase.id):
                await _plan_handoff(state, phase)

        # ---- WORK_c (fresh context) --------------------------------------
        # cycle 1: the current plan; cycle >= 2: the current plan plus the
        # previous review relay (the previous work result is already in
        # the plan's context — the relay distills the delta).
        phase = phase_factory("work")
        _log_event(
            "phase",
            id=phase.id,
            start=True,
            cycle=state.cycles,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        start_t = state.model.elapsed()
        with _phase_context(phase.id):
            result = await _run_phase_with_retries(
                state, phase, instrument, cycle=cycle
            )
        _log_event(
            "phase_done",
            id=phase.id,
            status=result.status,
            duration_s=round(state.model.elapsed() - start_t, 1),
            elapsed_s=round(state.model.elapsed(), 1),
        )
        if _model_endpoint_stalled(state):
            _log_event(
                "endpoint_stalled",
                phase=phase.id,
                failures=state.model.endpoint_failure_count,
            )
            return "done", _endpoint_finalize(state)
        save_state(state)
        if result.output is not None:
            output = getattr(result.output, "summary", "") or output
        if result.status == "timeout":
            # WORK time cap: one toolless final_ask on the same
            # conversation, then — in the last cycle — exit; between
            # cycles the relay still runs (it distills the cut-off state).
            with _phase_context(phase.id):
                await _final_ask(state, phase)
            final_status = "timeout"
        elif result.status == "error":
            final_status = "error"
        else:
            final_status = "done"
        _post_work_check(state)

        # ---- exit gate (last cycle) --------------------------------------
        if cycle >= n_cycles:
            _log_event(
                "run_finish",
                status=final_status,
                cycle=cycle,
                max_cycles=n_cycles,
                check=state.deliverable_check,
                elapsed_s=round(state.model.elapsed(), 1),
            )
            return final_status, output

        # ---- REVIEW_c relay (only between cycles) ------------------------
        # Toolless distillation on the resumed work transcript; typed
        # ReviewResult lands in state.results["review"] and is consumed by
        # the next PLAN and WORK. A relay timeout/error never blocks the
        # loop — the next cycle simply runs without the relay.
        cycle += 1
        state.cycles = cycle - 1
        _log_event(
            "cycle",
            reason="relay",
            cycle=state.cycles,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        phase = phase_factory("review")
        _log_event(
            "phase",
            id=phase.id,
            start=True,
            cycle=state.cycles,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        start_t = state.model.elapsed()
        with _phase_context(phase.id):
            result = await _run_phase_with_retries(
                state, phase, instrument, cycle=cycle
            )
        _log_event(
            "phase_done",
            id=phase.id,
            status=result.status,
            duration_s=round(state.model.elapsed() - start_t, 1),
            elapsed_s=round(state.model.elapsed(), 1),
        )
        if _model_endpoint_stalled(state):
            _log_event(
                "endpoint_stalled",
                phase=phase.id,
                failures=state.model.endpoint_failure_count,
            )
            return "done", _endpoint_finalize(state)
        save_state(state)
        if result.status in ("timeout", "error"):
            _log_event(
                "review_fallback",
                reason=result.status,
                cycle=state.cycles,
                error=result.error or "",
            )
        # The relay is never terminal and never retried further: the loop
        # continues to the next cycle's PLAN. (The old v6 verifier/repair/
        # salvage routing lived here and was replaced by the hard-cycle
        # regime; the phase files, prompts and config sections it used
        # stay on disk for a later re-enable — [tool_policy].disabled.)
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
        # v6-rewrite regime values: no time horizon, HARD cycle count
        # (env: SHLEPA_MAX_CYCLES, default 2); the entry is always "plan"
        # (a ``[agent].entry`` override is a dev knob).
        entry = cfg.agent.entry or "plan"
        max_steps: int | None = cfg.agent.max_steps or None  # dev knob, off by default
        max_cycles: int = max(1, int(cfg.agent.max_cycles or 2))

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
        # v6 (w3-6): tamper guard — record the in-environment test files
        # now; re-hashed before the run's own test results are accepted.
        state.test_hashes = bootstrap_test_hashes(workdir)
        _log_event("test_guard", files=len(state.test_hashes or {}))
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
            max_cycles=max_cycles,
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
        # v6 (w3-6): the run's own test results are only trustworthy if
        # the in-environment test files were not mutated mid-run.
        _verify_test_hashes(state)
        # v6-rewrite: best-at-exit is DISABLED (single source of truth is
        # the file after the last work). _restore_best_on_exit stays on
        # disk for a later re-enable; it is a no-op while snapshots are
        # off (no best_snapshot is ever taken).
        # _restore_best_on_exit(state)
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
