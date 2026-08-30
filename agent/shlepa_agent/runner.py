"""4-phase pipeline runner (v3).

Walks the phase graph:

    plan -> work -> (commit | replan -> plan, max N cycles)

with two escape valves:

- a phase hard-timeout (or any budget breach) triggers ONE extra toolless
  ``final_ask`` request on the same conversation ("write the deliverable
  now"), then hands off (plan -> work, work -> commit);
- crossing ``[agent].commit_deadline`` (520s) at a phase boundary while the
  next phase is not commit runs the emergency phase instead (terminal,
  full tools, until the global hard_time).

Rules:
- A budget breach (``BudgetExceeded`` / ``UsageLimitExceeded`` / persistent
  model ``ModelAPIError`` / phase time cap) is a NORMAL hand-off, never a
  retryable error.
- A phase ERROR (any other exception) in plan/work is retried up to the
  phase's ``max_retries`` (fresh run per attempt; the retried phase shares
  the global ``TrackedModel`` budget — no extra wall-clock allowance), then
  routes to commit. Terminal phases (commit, emergency) are never retried.
- The step guard (``[agent].max_steps``) bounds total phase runs; when it
  is exhausted the emergency phase runs, then the run stops.
- A phase is skipped when its wall-clock window is below
  ``MIN_RUN_WINDOW_S`` (there is nothing left to do).
- Never crash: any unexpected failure is logged as ``agent_error`` and the
  process exits 0 (a crash scores 0 anyway; a partial deliverable may score
  1).

Log contract (the CLI dev engine parses a subset — ``usage``,
``agent_start``, ``agent_done`` — keep those fields stable; unknown events
are ignored by the CLI): agent_start, usage, llm_thinking, llm_tool_call,
llm_tool_result, run_usage, budget, phase, phase_done, phase_retry,
final_ask, deadline, commit (legacy, terminal-phase skip marker),
agent_done, agent_error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from shlepa_agent.config import AgentConfig, load_config
from shlepa_agent.log import (
    _configure_logging,
    _log_event,
    _log_stream_event,
)
from shlepa_agent.model import BudgetExceeded, TrackedModel
from shlepa_agent.phases import get_phase
from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.template import load_prompt, render_system
from shlepa_agent.tools import AgentDeps, get_tools

#: Skip a phase run when less wall-clock time than this remains.
MIN_RUN_WINDOW_S = 10.0

#: Hard cap for the one-shot final_ask request after a phase time-out.
FINAL_ASK_CAP_S = 30.0

FINAL_ASK_MESSAGE = (
    "\u26a0\ufe0f HARD TIME LIMIT REACHED for this phase. Write the final "
    "deliverable NOW to the exact path in the exact format using only the "
    "information you already have. Do not call any tools and do not think "
    "any further: reply with one short line naming the deliverable path."
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


def _is_budget_error(exc: BaseException) -> bool:
    """True when a phase breach should hand off (budget result).

    Budget/limit breaches and persistent model errors (the server may
    recover inside the remaining window; the deliverable may already be
    partially usable). These are NOT retryable — only unexpected errors
    are.
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


async def _run_phase(
    state: RunState, phase: Phase, agent: Agent
) -> PhaseResult:
    """Run one phase under its wall-clock cap; returns its PhaseResult."""
    cfg = state.cfg
    model = state.model
    limits = phase.limits(cfg)
    remaining = max(0.0, cfg.budget.hard_time - model.elapsed())
    cap = min(limits.time, remaining) if limits.time is not None else remaining
    if cap < MIN_RUN_WINDOW_S:
        _log_event(
            "phase",
            id=phase.id,
            skipped=True,
            reason="not enough time left",
            cap_s=round(cap, 1),
            elapsed_s=round(model.elapsed(), 1),
        )
        return PhaseResult(status="budget", summary=f"{phase.id} skipped: no time left")
    model_settings: dict[str, Any] = {"temperature": cfg.agent.temp}
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
                usage_limits=UsageLimits(
                    request_limit=limits.requests,
                    total_tokens_limit=cfg.budget.token_budget,
                ),
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
        return PhaseResult(status="budget", error=f"{phase.id} time cap reached")
    except Exception as e:
        model.log_pending_usage()
        if _is_budget_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            return PhaseResult(status="budget", error=str(e)[:300])
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return PhaseResult(status="error", error=f"{type(e).__name__}: {str(e)[:300]}")


async def _run_phase_with_retries(
    state: RunState, phase: Phase, instrument: bool
) -> PhaseResult:
    """Run a phase; retry ERROR results up to its max_retries.

    Budget results are a normal hand-off (never retried), and the terminal
    phases are never retried. Each retry is a fresh run sharing the global
    TrackedModel budget. The result is stored in state.results after every
    attempt, so a retry's prompt can see the previous attempt.
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
    change routing: plan -> work, work -> commit.
    """
    cfg = state.cfg
    model = state.model
    remaining = max(0.0, cfg.budget.hard_time - model.elapsed())
    cap = min(FINAL_ASK_CAP_S, remaining)
    if cap < MIN_RUN_WINDOW_S:
        _log_event(
            "final_ask",
            phase=phase.id,
            skipped=True,
            reason="not enough time left",
            elapsed_s=round(model.elapsed(), 1),
        )
        return
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
        cap_s=round(cap, 1),
        history_messages=len(history or []),
        elapsed_s=round(model.elapsed(), 1),
    )
    try:
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                FINAL_ASK_MESSAGE,
                deps=state.deps,
                model_settings={"temperature": cfg.agent.temp},
                message_history=history,
            ) as events:
                async for event in events:
                    _log_stream_event(event)
        model.log_pending_usage()
        _log_event("final_ask", phase=phase.id, ok=True, elapsed_s=round(model.elapsed(), 1))
    except (TimeoutError, asyncio.TimeoutError):
        model.log_pending_usage()
        _log_event(
            "final_ask",
            phase=phase.id,
            ok=False,
            reason="time cap",
            elapsed_s=round(model.elapsed(), 1),
        )
    except Exception as e:
        model.log_pending_usage()
        _log_event(
            "final_ask",
            phase=phase.id,
            ok=False,
            error=f"{type(e).__name__}: {str(e)[:200]}",
        )


# ---------------------------------------------------------------------------
# Pipeline walk
# ---------------------------------------------------------------------------


async def _pipeline(
    state: RunState,
    instrument: bool,
    phase_factory: Callable[[str], Phase],
) -> tuple[str, str]:
    """Walk the 4-phase pipeline; returns (status, last_output).

    status is the decisive phase's status: "done" (the pipeline reached
    commit/emergency with a completed work/plan), "budget" (breach, cycle
    cap, or step-guard exhaustion), or "error" (a phase failed after its
    retries).
    """
    cfg = state.cfg
    phase_id = cfg.agent.entry
    steps = 0
    final_status = "done"
    output = ""
    while True:
        # Commit deadline at a phase boundary: past 520s and not heading to
        # commit -> emergency (until the global hard_time).
        if (
            phase_id not in ("commit", "emergency")
            and state.model.elapsed() >= cfg.agent.commit_deadline
        ):
            _log_event(
                "deadline",
                phase=phase_id,
                elapsed_s=round(state.model.elapsed(), 1),
                commit_deadline=cfg.agent.commit_deadline,
                hard_time=cfg.budget.hard_time,
            )
            phase_id = cfg.agent.emergency
        # Step guard: total phase runs exhausted -> emergency, then stop.
        if steps >= cfg.agent.max_steps and phase_id not in ("commit", "emergency"):
            _log_event(
                "budget",
                reason="max_steps",
                detail=f"step guard {cfg.agent.max_steps} exhausted",
            )
            phase_id = cfg.agent.emergency
        steps += 1
        phase = phase_factory(phase_id)
        _log_event(
            "phase",
            id=phase.id,
            start=True,
            cycle=state.cycles,
            requests=phase.limits(cfg).requests,
            elapsed_s=round(state.model.elapsed(), 1),
        )
        start_t = state.model.elapsed()
        result = await _run_phase_with_retries(state, phase, instrument)
        _log_event(
            "phase_done",
            id=phase.id,
            status=result.status,
            duration_s=round(state.model.elapsed() - start_t, 1),
            elapsed_s=round(state.model.elapsed(), 1),
        )
        # Track the human-readable final output (terminal text wins).
        if result.summary:
            if phase.id == "work" and result.output is not None:
                output = result.output.summary or output
            elif phase.terminal:
                output = result.summary
            elif phase.id != "plan":
                output = result.summary
        if phase.terminal:
            return (
                final_status if final_status in ("budget", "error") else "done",
                output,
            )
        decision = getattr(result.output, "decision", None)
        if phase.id == "plan":
            if result.status == "budget":
                # Hard timeout / budget breach: one toolless final_ask on the
                # same conversation, then execute whatever the plan knows.
                await _final_ask(state, phase)
                final_status = "budget"
                phase_id = "work"
                continue
            if result.status == "error":
                final_status = "error"
                phase_id = "commit"
                continue
            if decision == "commit":
                # Trivial task: the plan already knows the answer.
                final_status = "done"
                phase_id = "commit"
                continue
            final_status = "done"
            phase_id = "work"
            continue
        if phase.id == "work":
            if result.status == "budget":
                await _final_ask(state, phase)
                final_status = "budget"
                phase_id = "commit"
                continue
            if result.status == "error":
                final_status = "error"
                phase_id = "commit"
                continue
            if decision == "replan":
                state.cycles += 1
                if state.cycles < cfg.agent.max_cycles:
                    final_status = "done"
                    phase_id = "plan"
                    continue
                _log_event(
                    "budget",
                    reason="max_cycles",
                    detail=f"replan cycle cap {cfg.agent.max_cycles} reached",
                )
                final_status = "budget"
                phase_id = "commit"
                continue
            final_status = "done"
            phase_id = "commit"
            continue
        # Unknown phase id: stop the walk (defensive).
        return result.status, output


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
    cfg = agent_cfg or load_config()
    model: TrackedModel | None = None
    try:
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
            temp=cfg.agent.temp,
            soft_time=cfg.budget.soft_time,
            hard_time=cfg.budget.hard_time,
            request_limit=cfg.budget.request_limit,
            token_budget=cfg.budget.token_budget,
            entry=cfg.agent.entry,
            emergency=cfg.agent.emergency,
            max_cycles=cfg.agent.max_cycles,
            commit_deadline=cfg.agent.commit_deadline,
        )
        factory = phase_factory or get_phase
        status, output = await _pipeline(state, instrument, factory)
        model.log_pending_usage()
        _log_event(
            "agent_done",
            status=status,
            elapsed_s=round(model.elapsed(), 1),
            output=output,
        )
        return output
    except Exception as e:
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        elapsed = round(model.elapsed(), 1) if model is not None else 0.0
        _log_event("agent_done", status="error", elapsed_s=elapsed, output="")
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
