"""v3 loop regime: the budgeted main phase -> terminal commit.

The control flow of the registered v3 agent (MLflow model version 3, run
ee78c24c) on top of the v5 modular toolset/config/model machinery:

- ONE open main phase: the full tool loop (the arm's toolset, free text —
  no typed output), bounded NOT by a per-phase cap but by the depleting
  ``[v3loop]`` budget: soft/hard wall-clock checks before every LLM
  request (:class:`BudgetedModel`), plus the request-count and total-token
  budgets via pydantic-ai ``UsageLimits``.
- On a budget breach (``BudgetExceeded`` / ``UsageLimitExceeded``) or a
  persistent model error the run hands off to the TERMINAL commit phase:
  one short window (``commit_time_cap``, capped at the remaining hard
  window) to write the deliverable from the information already gathered.
  A normal main finish does NOT trigger the commit (v3 parity: the main
  run already wrote the deliverable); a non-budget error ends the run
  without a commit.

The loop axis is orthogonal to the toolset arms (``toolsets.py``): the v3
regime runs with any arm. Selected via ``[agent].loop`` / ``SHLEPA_LOOP``;
the default regime is the v5 cycles pipeline (``runner.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from shlepa_agent.config import AgentConfig, load_config
from shlepa_agent.log import _configure_logging, _log_event, _log_stream_event
from shlepa_agent.model import BudgetExceeded, TrackedModel
from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.state import save_state
from shlepa_agent.template import load_prompt, render_system
from shlepa_agent.tools import AgentDeps, get_tools

#: A commit window shorter than this cannot write + verify anything; the
#: commit is skipped with a log event instead (v3 parity).
COMMIT_MIN_CAP_S = 10.0


class BudgetedModel(TrackedModel):
    """TrackedModel with the v3 depleting budget (soft/hard wall gates).

    v3 semantics: before every LLM request the elapsed wall time is
    checked against the ``[v3loop]`` soft/hard budgets; a breach raises
    :class:`~shlepa_agent.model.BudgetExceeded`, which the pipeline hands
    off to the terminal commit phase. The commit phase disables the soft
    check (``enable_soft_check = False``) so it can spend the remaining
    hard window; the hard check stays active in both phases. The
    request-count and total-token budgets are enforced by pydantic-ai
    ``UsageLimits`` in the pipeline (v3 parity), and the per-request wall
    uses ``[v3loop].request_wall`` (240s) instead of the cycles regime's
    fixed 180s ``LLM_WALL``.
    """

    def __init__(self, model_name: str, provider: OpenAIProvider, agent_cfg: AgentConfig):
        super().__init__(model_name, provider, agent_cfg)
        v3 = agent_cfg.v3loop
        self.soft_time = v3.soft_time
        self.hard_time = v3.hard_time
        self.request_wall = v3.request_wall
        # The stream wall cap uses the v3 value (request_wall), not the
        # cycles regime's fixed LLM_WALL.
        self.llm_wall = v3.request_wall
        #: Soft-budget gate; the commit phase disables it (the hard check
        #: stays active so the commit cannot run past the hard window).
        self.enable_soft_check = True

    # -- budget gates (v3 _open_stream semantics) -------------------------
    def _soft_expired(self) -> bool:
        return self.enable_soft_check and self.elapsed() > self.soft_time

    def _hard_expired(self) -> bool:
        return self.elapsed() > self.hard_time

    def _budget_check(self) -> None:
        """Pre-request gate: raises BudgetExceeded on a soft/hard breach."""
        if self._hard_expired():
            raise BudgetExceeded(f"hard time limit {self.hard_time:.0f}s exceeded")
        if self._soft_expired():
            raise BudgetExceeded(
                f"soft time limit {self.soft_time:.0f}s exceeded before request"
            )

    # -- overrides ----------------------------------------------------------
    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[Any],
        model_settings: Any,
        model_request_parameters: Any,
        run_context: Any = None,
    ):
        self._budget_check()
        async with super().request_stream(
            messages, model_settings, model_request_parameters, run_context
        ) as stream:
            yield stream

    async def request(
        self,
        messages: list[Any],
        model_settings: Any,
        model_request_parameters: Any,
    ) -> Any:
        self._budget_check()
        return await super().request(messages, model_settings, model_request_parameters)


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


class MainPhase(Phase):
    """The v3 single open main phase (id ``main``).

    Free text (NO typed output): the model's final answer is the run's
    output, exactly like the v3 agent. Tools come from ``[phases.main]``
    (the arm's toolset). The wall is NOT a per-phase cap: the run is
    bounded by the depleting ``[v3loop]`` budget (the ``BudgetedModel``
    soft/hard gates + the ``UsageLimits`` request/token budgets), so
    ``limits`` here are advisory only.
    """

    id = "main"
    output_type = None
    terminal = False

    def prompt(self, state: RunState) -> str:
        # The task is the user message (v3 parity); the protocol and the
        # rendered budget line live in the system message (main.md).
        return state.task


class V3CommitPhase(Phase):
    """The v3 TERMINAL commit phase (id ``commit``).

    Free text (the cycles regime's commit is typed — ReviewResult; here the
    deliverable is already on disk and the phase only writes/verifies it)."""

    id = "commit"
    output_type = None
    terminal = True

    def history(self, state: RunState) -> list[Any] | None:
        # Resumes the MAIN conversation (trimmed: no dangling tool calls).
        return trim_history(state.model.last_messages)

    def prompt(self, state: RunState) -> str:
        prompt = load_prompt("v3commit.md")
        if not self.history(state):
            # No conversation to resume: re-state the task so the commit
            # run has context (v3 parity).
            prompt = prompt + "\n\nORIGINAL TASK:\n" + state.task
        return prompt


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------


def _budget_line(cfg: AgentConfig) -> str:
    """The one rendered budget line for the main prompt's BUDGET section."""
    v3 = cfg.v3loop
    return (
        f"- This run's budget: {v3.soft_time:.0f}s soft and {v3.hard_time:.0f}s hard wall "
        f"clock, at most {v3.request_limit} LLM requests and {v3.token_budget} total tokens. "
        "A budget breach interrupts this phase and hands off to the commit phase."
    )


def _main_system_prompt(cfg: AgentConfig) -> str:
    """System message for the v3 main phase.

    ``prompts/main.md`` carries the adapted v3 SYSTEM_PROMPT sections
    (PROTOCOL / FORMAT DISCIPLINE / CODE FIX TASKS / BUDGET); the tool
    block comes from the arm's toolset (``[phases.main].tools``) and the
    BUDGET section gains one line rendered from the ``[v3loop]`` values.
    The task is NOT in the system message — it is the user message.
    """
    tools = get_tools(cfg, MainPhase().tools(cfg))
    tools_block = "\n".join(f"- {tool.note}" for tool in tools)
    if any(tool.name == "mitre_kb" for tool in tools):
        from shlepa_agent.mitre_kb import kb_prefix

        tools_block += "\n\n" + kb_prefix()
    system = load_prompt("main.md") + "\n" + _budget_line(cfg)
    return render_system(cfg, "main", {"system": system, "tools": tools_block})


def build_main_agent(model: BudgetedModel, cfg: AgentConfig, instrument: bool = False) -> Agent:
    """The main-phase agent: full toolset, free text (no output_type)."""
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_main_system_prompt(cfg),
        name="main",
    )
    if instrument:
        agent.instrument = True
    for tool in get_tools(cfg, MainPhase().tools(cfg)):
        agent.tool(tool.run)
    return agent


def build_commit_agent(model: BudgetedModel, cfg: AgentConfig, instrument: bool = False) -> Agent:
    """The terminal commit agent.

    Same system message as the main phase: a resumed history already
    carries the system request (pydantic-ai does not re-add the agent's
    system prompt to a non-empty history), and the empty-history edge
    case still gets it. Tools come from ``[phases.commit]`` (shared with
    the cycles regime).
    """
    agent = Agent(
        model,
        deps_type=AgentDeps,
        system_prompt=_main_system_prompt(cfg),
        name="commit",
    )
    if instrument:
        agent.instrument = True
    for tool in get_tools(cfg, V3CommitPhase().tools(cfg)):
        agent.tool(tool.run)
    return agent


def _model_settings(cfg: AgentConfig) -> dict[str, Any]:
    """Per-request model settings (same contract as the cycles runner).

    Temperature is sent only when ``agent.send_temp`` is enabled.
    """
    settings: dict[str, Any] = {}
    if cfg.agent.send_temp:
        settings["temperature"] = cfg.agent.temp
    return settings


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------


def _is_handoff_error(exc: BaseException) -> bool:
    """True when the main run's breach is a normal hand-off to the commit.

    Budget breaches (soft/hard wall clock, request-count, total-token)
    and persistent model errors: the deliverable may already be partially
    usable, and the commit phase gets the last word. Anything else is an
    error that ends the run without a commit (v3 parity).
    """
    e: BaseException | None = exc
    seen: set[int] = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, (BudgetExceeded, UsageLimitExceeded, ModelAPIError)):
            return True
        e = e.__cause__ or e.__context__
    return False


async def _run_main(state: RunState, instrument: bool) -> tuple[str, str]:
    """Run the v3 main phase; returns (status, output).

    status: "done" (the run finished normally), "budget" (a budget/limit
    breach or persistent model error — hand off to the commit), "error"
    (any other failure — no commit).
    """
    cfg = state.cfg
    model = state.model
    v3 = cfg.v3loop
    phase = MainPhase()
    model.current_phase = phase.id
    model.enable_soft_check = True
    _log_event("phase", id=phase.id, start=True, elapsed_s=round(model.elapsed(), 1))
    start_t = model.elapsed()
    output = ""
    try:
        agent = build_main_agent(model, cfg, instrument)
        async with agent.run_stream_events(
            phase.prompt(state),
            deps=state.deps,
            model_settings=_model_settings(cfg),
            usage_limits=UsageLimits(
                request_limit=v3.request_limit,
                total_tokens_limit=v3.token_budget,
            ),
        ) as events:
            async for event in events:
                out = _log_stream_event(event)
                if out is not None:
                    output = out
        model.log_pending_usage()
        _log_event(
            "phase_done",
            id=phase.id,
            status="done",
            duration_s=round(model.elapsed() - start_t, 1),
            elapsed_s=round(model.elapsed(), 1),
        )
        return "done", output
    except Exception as e:
        model.log_pending_usage()
        if _is_handoff_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            _log_event(
                "phase_done",
                id=phase.id,
                status="timeout",
                duration_s=round(model.elapsed() - start_t, 1),
                elapsed_s=round(model.elapsed(), 1),
            )
            return "budget", output
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        _log_event(
            "phase_done",
            id=phase.id,
            status="error",
            duration_s=round(model.elapsed() - start_t, 1),
            elapsed_s=round(model.elapsed(), 1),
        )
        return "error", output


async def _run_commit(state: RunState, instrument: bool) -> None:
    """Run the terminal commit phase. NEVER fails the run.

    The commit may spend the whole remaining hard window (the soft check
    is disabled, the hard check stays active); its cap is
    ``min(commit_time_cap, hard_time - elapsed)`` and below
    ``COMMIT_MIN_CAP_S`` the commit is skipped with a log event. The
    request-count budget is ``[v3loop].commit_request_limit`` and the
    reasoning effort comes from ``[phases.commit].reasoning_effort``.
    """
    cfg = state.cfg
    model = state.model
    v3 = cfg.v3loop
    phase = V3CommitPhase()
    remaining = max(0.0, v3.hard_time - model.elapsed())
    cap = min(v3.commit_time_cap, remaining)
    if cap < COMMIT_MIN_CAP_S:
        _log_event(
            "commit",
            skipped=True,
            reason="not enough time left",
            elapsed_s=round(model.elapsed(), 1),
        )
        return
    # The commit is allowed to spend the remaining hard-time window.
    model.enable_soft_check = False
    model.current_phase = phase.id
    history = phase.history(state) or None
    model_settings = _model_settings(cfg)
    effort = phase.limits(cfg).reasoning_effort
    if effort is not None:
        model_settings["openai_reasoning_effort"] = effort
    _log_event(
        "commit",
        start=True,
        phase=phase.id,
        history_messages=len(history or []),
        time_cap_s=round(cap, 1),
        elapsed_s=round(model.elapsed(), 1),
    )
    try:
        agent = build_commit_agent(model, cfg, instrument)
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                phase.prompt(state),
                deps=state.deps,
                model_settings=model_settings,
                message_history=history,
                usage_limits=UsageLimits(request_limit=v3.commit_request_limit),
            ) as events:
                async for event in events:
                    _log_stream_event(event)
        model.log_pending_usage()
        _log_event("commit", done=True, elapsed_s=round(model.elapsed(), 1))
    except (TimeoutError, asyncio.TimeoutError):
        model.log_pending_usage()
        _log_event(
            "commit",
            done=True,
            note="commit time cap reached",
            elapsed_s=round(model.elapsed(), 1),
        )
    except Exception as e:
        model.log_pending_usage()
        _log_event(
            "commit", done=True, error=f"{type(e).__name__}: {str(e)[:300]}"
        )


# ---------------------------------------------------------------------------
# Pipeline walk
# ---------------------------------------------------------------------------


async def run_v3loop(state: RunState, instrument: bool = False) -> tuple[str, str]:
    """The v3 loop regime: main -> (budget -> terminal commit).

    Returns (status, output). "done": the main run finished normally (NO
    commit — it already wrote the deliverable, v3 parity); "budget": a
    budget/limit/model-error hand-off, the commit phase ran (or was
    skipped for lack of time); "error": a non-budget failure, NO commit.
    Never raises.
    """
    status, output = await _run_main(state, instrument)
    state.results[MainPhase.id] = PhaseResult(
        status={"done": "done", "budget": "timeout"}.get(status, "error"),
        summary=output[:4000],
    )
    save_state(state)
    if status == "budget":
        await _run_commit(state, instrument)
        save_state(state)
    return status, output


# ---------------------------------------------------------------------------
# Entry point (same env contract as the cycles runner)
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


def _make_model(
    model_name: str, provider: OpenAIProvider, cfg: AgentConfig
) -> BudgetedModel:
    """Model factory (module-level so tests can swap it / age the clock)."""
    return BudgetedModel(model_name, provider, cfg)


async def run_prompt(
    prompt: str,
    instrument: bool = False,
    agent_cfg: AgentConfig | None = None,
) -> str:
    """Run the v3 loop regime for one task prompt; returns the final output.

    Never raises: any unexpected failure is logged as agent_error (+ a
    final agent_done with status "error") and "" is returned, so the
    process exits 0 (a crash scores 0 anyway).
    """
    _configure_logging()
    cfg = agent_cfg or load_config()
    model: BudgetedModel | None = None
    try:
        workdir = _resolve_workdir()
        model = _make_model(
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
        v3 = cfg.v3loop
        _log_event(
            "agent_start",
            model=_resolve_model_name(),
            base_url=_required_env("OPENAI_BASE_URL"),
            workdir=str(workdir),
            prompt=prompt,
            loop="v3",
            # reported only when it is actually sent to the endpoint (#65)
            **({"temp": cfg.agent.temp} if cfg.agent.send_temp else {}),
            # named toolset arm (agent/shlepa_agent/toolsets.py); the
            # default baseline keeps the log byte-identical
            **({"arm": cfg.arm} if cfg.arm != "baseline" else {}),
            # the depleting v3 budget (CLI ignores unknown fields)
            soft_time=round(v3.soft_time, 1),
            hard_time=round(v3.hard_time, 1),
            request_limit=v3.request_limit,
            token_budget=v3.token_budget,
            commit_time_cap=round(v3.commit_time_cap, 1),
            commit_request_limit=v3.commit_request_limit,
            request_wall=round(v3.request_wall, 1),
        )
        save_state(state)
        status, output = await run_v3loop(state, instrument)
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
    parser = argparse.ArgumentParser(
        description="Run local non-interactive coding agent (v3 loop regime)"
    )
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
