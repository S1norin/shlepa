"""Phase-graph runner for the v2 agent.

Walks the configured phase graph:

    entry phase -> run -> PhaseResult -> route() -> next phase id | None

Rules:
- A budget breach (``BudgetExceeded`` / ``UsageLimitExceeded`` / persistent
  model ``ModelAPIError``) is a NORMAL hand-off to the emergency phase,
  never a retryable error.
- A phase ERROR (any other exception) in a regular phase is retried up to
  the phase's ``max_retries`` (fresh run per attempt; the retried phase
  shares the global ``TrackedModel`` budget — no extra wall-clock
  allowance), then routes to the emergency phase. The emergency phase
  itself is never retried: it is the last line of defense, its outcome is
  reported in the ``commit`` events, and re-running it would only burn the
  remaining wall-clock window.
- The step guard (``[agent].max_steps``) bounds total phase runs; when it
  is exhausted the emergency phase runs once more, then the run stops.
- The emergency phase has a hard wall-clock cap (``min(phase time, remaining
  hard time)``); with less than a minimal window left it is skipped.
- Never crash: any unexpected failure is logged as ``agent_error`` and the
  process exits 0 (a crash scores 0 anyway; a partial deliverable may score 1).

Log contract (the CLI dev engine parses a subset — ``usage``,
``agent_start``, ``agent_done`` — keep those fields stable; unknown events
are ignored by the CLI): agent_start, usage, llm_thinking, llm_tool_call,
llm_tool_result, run_usage, budget, commit, phase_retry, agent_done,
agent_error.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

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
from shlepa_agent.template import load_prompt, render_system
from shlepa_agent.tools import AgentDeps, get_tools

#: Skip the emergency phase when less wall-clock time than this remains.
MIN_EMERGENCY_WINDOW_S = 10.0


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
    """True when a phase breach should hand off to the emergency phase.

    Budget/limit breaches and persistent model errors (the server may recover
    inside the emergency window; the deliverable may already be partially
    usable). These are NOT retryable — only unexpected errors are.
    """
    e: BaseException | None = exc
    seen: set[int] = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (BudgetExceeded, UsageLimitExceeded, ModelAPIError)):
            return True
        if "BudgetExceeded" in type(e).__name__ or "soft time limit" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def build_phase_agent(
    model: TrackedModel,
    agent_cfg: AgentConfig,
    phase: Phase,
    instrument: bool = False,
) -> Agent[AgentDeps, str]:
    """Build a pydantic-ai agent for one phase (toolset from phase config).

    The system prompt is rendered from the common request template (base.md
    plus the per-tool usage notes); tool descriptions themselves live in the
    tool modules (pydantic-ai tool spec).
    """
    tools = get_tools(agent_cfg, phase.tools(agent_cfg))
    system = render_system(
        agent_cfg,
        phase.id,
        {
            "system": load_prompt("base.md"),
            "tools": "\n".join(f"- {tool.note}" for tool in tools),
        },
    )
    agent = Agent(model, deps_type=AgentDeps, system_prompt=system)
    if instrument:
        agent.instrument = True
    for tool in tools:
        agent.tool(tool.run)
    return agent


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------


async def _run_normal_phase(
    state: RunState, phase: Phase, agent: Agent[AgentDeps, str]
) -> PhaseResult:
    """Run a regular (non-terminal) phase; returns its PhaseResult."""
    cfg = state.cfg
    model = state.model
    limits = phase.limits(cfg)
    model_settings: dict[str, Any] = {"temperature": cfg.agent.temp}
    if limits.reasoning_effort is not None:
        model_settings["openai_reasoning_effort"] = limits.reasoning_effort
    output = ""
    try:
        async with agent.run_stream_events(
            phase.prompt(state),
            deps=state.deps,
            model_settings=model_settings,
            usage_limits=UsageLimits(
                request_limit=limits.requests,
                total_tokens_limit=cfg.budget.token_budget,
            ),
            message_history=phase.history(state),
        ) as events:
            async for event in events:
                out = _log_stream_event(event)
                if out is not None:
                    output = out
        model.log_pending_usage()
        return PhaseResult(status="done", summary=output)
    except Exception as e:
        model.log_pending_usage()
        if _is_budget_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            return PhaseResult(status="budget", error=str(e)[:300])
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return PhaseResult(
            status="error", error=f"{type(e).__name__}: {str(e)[:300]}"
        )


async def _run_terminal_phase(
    state: RunState, phase: Phase, agent: Agent[AgentDeps, str]
) -> PhaseResult:
    """Run the emergency phase under its hard wall-clock cap."""
    cfg = state.cfg
    model = state.model
    limits = phase.limits(cfg)
    remaining = max(0.0, cfg.budget.hard_time - model.elapsed())
    cap = min(limits.time, remaining)
    if cap < MIN_EMERGENCY_WINDOW_S:
        _log_event(
            "commit",
            skipped=True,
            reason="not enough time left",
            elapsed_s=round(model.elapsed(), 1),
        )
        return PhaseResult(status="done", summary="emergency phase skipped")
    # The emergency phase is allowed to spend the remaining hard-time window.
    model.enable_soft_check = False
    history = phase.history(state)
    model_settings: dict[str, Any] = {"temperature": cfg.agent.temp}
    if limits.reasoning_effort is not None:
        model_settings["openai_reasoning_effort"] = limits.reasoning_effort
    _log_event(
        "commit",
        start=True,
        history_messages=len(history or []),
        time_cap_s=round(cap, 1),
        elapsed_s=round(model.elapsed(), 1),
    )
    output = ""
    try:
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                phase.prompt(state),
                deps=state.deps,
                model_settings=model_settings,
                usage_limits=UsageLimits(request_limit=limits.requests),
                message_history=history,
            ) as events:
                async for event in events:
                    out = _log_stream_event(event)
                    if out is not None:
                        output = out
        model.log_pending_usage()
        _log_event("commit", done=True, elapsed_s=round(model.elapsed(), 1))
        return PhaseResult(status="done", summary=output)
    except (TimeoutError, asyncio.TimeoutError):
        model.log_pending_usage()
        _log_event(
            "commit",
            done=True,
            note="commit time cap reached",
            elapsed_s=round(model.elapsed(), 1),
        )
        return PhaseResult(status="budget", summary="commit time cap reached")
    except Exception as e:
        model.log_pending_usage()
        _log_event(
            "commit", done=True, error=f"{type(e).__name__}: {str(e)[:300]}"
        )
        if _is_budget_error(e):
            return PhaseResult(status="budget", error=str(e)[:300])
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return PhaseResult(status="error", error=f"{type(e).__name__}: {str(e)[:300]}")


async def _run_phase(
    state: RunState, phase: Phase, agent: Agent[AgentDeps, str]
) -> PhaseResult:
    if phase.terminal:
        return await _run_terminal_phase(state, phase, agent)
    return await _run_normal_phase(state, phase, agent)


async def _run_phase_with_retries(
    state: RunState, phase: Phase, instrument: bool
) -> PhaseResult:
    """Run a phase; retry ERROR results up to its max_retries.

    Budget results are a normal hand-off (never retried), and the terminal
    (emergency) phase is never retried. Each retry is a fresh run sharing
    the global TrackedModel budget.
    """
    result = await _run_phase(state, phase, build_phase_agent(state.model, state.cfg, phase, instrument))
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
            state, phase, build_phase_agent(state.model, state.cfg, phase, instrument)
        )
    return result


# ---------------------------------------------------------------------------
# Phase-graph walk
# ---------------------------------------------------------------------------


async def _walk(
    state: RunState,
    instrument: bool,
    phase_factory: Callable[[str], Phase],
) -> tuple[str, str]:
    """Walk the phase graph; returns (status, last_output).

    status is the decisive phase's status: "done" (entry finished its job),
    "budget" (breach or step-guard exhaustion), or "error" (a phase failed
    after its retries).
    """
    cfg = state.cfg
    phase_id = cfg.agent.entry
    steps = 0
    final_status: str | None = None
    output = ""
    while True:
        guard_hit = steps >= cfg.agent.max_steps
        if guard_hit:
            _log_event(
                "budget",
                reason="max_steps",
                detail=f"step guard {cfg.agent.max_steps} exhausted",
            )
            phase_id = cfg.agent.emergency
        steps += 1
        phase = phase_factory(phase_id)
        result = await _run_phase_with_retries(state, phase, instrument)
        state.results[phase.id] = result
        if result.summary:
            output = result.summary
        if guard_hit:
            return "budget", output
        next_id = phase.route(result, state)
        if next_id is None:
            if phase.terminal:
                # The emergency phase ended the run: keep the decisive status
                # of the phase that routed here.
                return (final_status or result.status), output
            return result.status, output
        final_status = result.status
        phase_id = next_id


async def run_prompt(
    prompt: str,
    instrument: bool = False,
    agent_cfg: AgentConfig | None = None,
    phase_factory: Callable[[str], Phase] | None = None,
) -> str:
    """Run the full phase pipeline for one task prompt; returns final output.

    Never raises: any unexpected failure is logged as agent_error (+ a final
    agent_done with status "error") and "" is returned, so the process exits 0.
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
            deps=AgentDeps(workdir=workdir, cfg=cfg),
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
        )
        factory = phase_factory or get_phase
        status, output = await _walk(state, instrument, factory)
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
