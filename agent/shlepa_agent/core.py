"""Shlepa agent (v1): budgeted main phase + commit phase.

Ported from the 2026-08-24 submission (registered as shlepa:3 in the MLflow
model registry), replacing the plain vendored upstream baseline with the v1
design:

- Main phase: stream a pydantic-ai agent run with a request limit and a soft
  total-token budget. The budget/limit breach raises UsageLimitExceeded
  (pydantic-ai) or BudgetExceeded (our model), which triggers the commit phase.
- Commit phase: resume the SAME conversation (trimmed message history) with a
  short "write the deliverable now" prompt under a strict time cap.
- TrackedModel(OpenAIChatModel, shlepa_agent/model.py): per-request usage
  logging, wall-clock budget checks, one retry for transient network errors,
  context-overflow detection, full-text llm_thinking events.
- Never crash: any unexpected failure is logged as agent_error and the process
  exits 0 (a crash scores 0 anyway; a partial deliverable may score 1).

Telemetry is opt-in via the ``instrument`` flag (see ``__main__.py``); this
module never imports the otel SDK stack.
"""

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, UsageLimitExceeded
from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from shlepa_agent.config import AgentConfig, load_config as load_agent_config
from shlepa_agent.log import (
    _configure_logging,
    _log_event,
    _log_stream_event,
)
from shlepa_agent.model import BudgetExceeded, TrackedModel
from shlepa_agent.template import render_system, render_user
from shlepa_agent.tools import AgentDeps, get_tools

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    """Read a prompt file (prompts/*.md), stripped of surrounding whitespace."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()


@dataclass(frozen=True)
class Config:
    temp: float
    hard_time: float
    soft_time: float
    commit_time_cap: float
    request_limit: int
    commit_request_limit: int
    token_budget: int
    bash_timeout: float
    request_timeout: float
    request_wall: float
    max_tokens: int
    max_tool_output: int
    commit_reasoning_effort: str


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default) or default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def load_config() -> Config:
    return Config(
        temp=_env_float("AGENT_TEMP", 0.2),
        # Task agent timeout is 600s (closed set). Budgets stay under it with margin:
        # soft fire at ~500s, commit window up to 80s, process done by ~585s.
        hard_time=_env_float("AGENT_HARD_TIME", 585.0),
        soft_time=_env_float("AGENT_SOFT_TIME", 500.0),
        commit_time_cap=_env_float("AGENT_COMMIT_TIME_CAP", 80.0),
        request_limit=_env_int("AGENT_REQUEST_LIMIT", 90),
        commit_request_limit=_env_int("AGENT_COMMIT_REQUEST_LIMIT", 25),
        token_budget=_env_int("AGENT_TOKEN_BUDGET", 300000),
        bash_timeout=_env_float("AGENT_BASH_TIMEOUT", 120.0),
        request_timeout=_env_float("AGENT_REQUEST_TIMEOUT", 180.0),
        # Kill a single in-flight request if it runs this long (open -> last
        # chunk). Prevents one very slow generation (e.g. a long thinking
        # stream on a degraded server) from eating the whole budget and
        # leaving no commit window. Healthy requests finish in 10-120s.
        request_wall=_env_float("AGENT_REQUEST_WALL", 240.0),
        # Hard per-request output cap. Without it a single request can loop
        # for tens of thousands of tokens (observed: 45k in one turn) and eat
        # the whole trial before the commit phase can run.
        max_tokens=_env_int("AGENT_MAX_TOKENS", 16384),
        max_tool_output=_env_int("AGENT_MAX_TOOL_OUTPUT", 16000),
        # Commit run should act, not think: low reasoning effort keeps the
        # commit inside its (short) time window. Main run keeps the server
        # default (medium) so hard tasks still get real reasoning.
        commit_reasoning_effort=_env_str("AGENT_COMMIT_REASONING_EFFORT", "low"),
    )


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


def _trim_history(messages: list[Any]) -> list[Any]:
    """Build a safe message history for the commit-phase run.

    - Drop the trailing user/retry prompt (the commit prompt replaces it).
    - Drop a trailing model response with unpaired tool calls (would 400).
    A trailing tool-return request is kept: it is a valid open state.
    """
    msgs = list(messages)
    if msgs and isinstance(msgs[-1], ModelRequest):
        has_tool_return = any(isinstance(p, ToolReturnPart) for p in msgs[-1].parts)
        if not has_tool_return:
            msgs.pop()
    while msgs and isinstance(msgs[-1], ModelResponse):
        if any(isinstance(p, ToolCallPart) for p in msgs[-1].parts):
            msgs.pop()
            continue
        break
    return msgs


def _is_budget_error(exc: BaseException) -> bool:
    """True when the main run should hand off to the commit phase.

    Budget/limit breaches and persistent model errors (the server may recover
    inside the commit window; the deliverable may already be partially usable).
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


def get_pydantic_agent(
    model: TrackedModel,
    agent_cfg: AgentConfig,
    phase_id: str,
    tool_names: list[str],
    instrument: bool = False,
) -> Agent[AgentDeps, str]:
    """Build a pydantic-ai agent with the configured tool subset.

    The system prompt is rendered from the common request template (base.md
    plus the per-tool usage notes); tool descriptions themselves live in the
    tool modules (pydantic-ai tool spec). ``tool_names`` comes from a phase's
    config (``[phases.<id>].tools``).
    """
    tools = get_tools(agent_cfg, tool_names)
    system = render_system(
        agent_cfg,
        phase_id,
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
# Run: main phase + commit phase
# ---------------------------------------------------------------------------

async def _run_main(
    agent: Agent[AgentDeps, str],
    model: TrackedModel,
    cfg: Config,
    prompt: str,
    deps: AgentDeps,
) -> tuple[str, str]:
    """Returns (status, output); status in {'done', 'budget', 'error'}."""
    output = ""
    try:
        async with agent.run_stream_events(
            prompt,
            deps=deps,
            model_settings={"temperature": cfg.temp},
            usage_limits=UsageLimits(
                request_limit=cfg.request_limit,
                total_tokens_limit=cfg.token_budget,
            ),
        ) as events:
            async for event in events:
                out = _log_stream_event(event)
                if out is not None:
                    output = out
        model.log_pending_usage()
        return "done", output
    except Exception as e:
        model.log_pending_usage()
        if _is_budget_error(e):
            _log_event("budget", reason="usage_or_time", detail=str(e)[:200])
            return "budget", output
        _log_event("agent_error", error=f"{type(e).__name__}: {str(e)[:500]}")
        return "error", output


async def _run_commit(
    agent: Agent[AgentDeps, str],
    model: TrackedModel,
    cfg: Config,
    deps: AgentDeps,
    prompt: str,
) -> None:
    remaining = max(0.0, cfg.hard_time - model.elapsed())
    cap = min(cfg.commit_time_cap, remaining)
    if cap < 10:
        _log_event(
            "commit",
            skipped=True,
            reason="not enough time left",
            elapsed_s=round(model.elapsed(), 1),
        )
        return
    history = _trim_history(model.last_messages)
    # Commit message: the common template rendered for the emergency phase.
    # The task block is repeated only when there is no history to resume
    # (otherwise the task is already in the conversation).
    commit_id = deps.cfg.agent.emergency
    commit_contents: dict[str, str] = {"phase_prompt": load_prompt(f"{commit_id}.md")}
    if not history:
        commit_contents["task"] = prompt
    commit_prompt = render_user(deps.cfg, commit_id, commit_contents)
    # The commit phase is allowed to spend the remaining hard-time window.
    model.enable_soft_check = False
    _log_event(
        "commit",
        start=True,
        history_messages=len(history),
        time_cap_s=round(cap, 1),
        elapsed_s=round(model.elapsed(), 1),
    )
    try:
        async with asyncio.timeout(cap):
            async with agent.run_stream_events(
                commit_prompt,
                deps=deps,
                model_settings={
                    "temperature": cfg.temp,
                    "openai_reasoning_effort": cfg.commit_reasoning_effort,
                },
                message_history=history,
                usage_limits=UsageLimits(request_limit=cfg.commit_request_limit),
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
        _log_event("commit", done=True, error=f"{type(e).__name__}: {str(e)[:300]}")


async def run_prompt(prompt: str, instrument: bool = False) -> str:
    _configure_logging()
    cfg = load_config()
    workdir = _resolve_workdir()
    agent_cfg = load_agent_config()
    model = TrackedModel(
        _resolve_model_name(),
        OpenAIProvider(
            base_url=_required_env("OPENAI_BASE_URL"),
            api_key=_required_env("OPENAI_API_KEY"),
        ),
        agent_cfg,
    )
    phase_id = agent_cfg.agent.entry
    phase = agent_cfg.phases[phase_id]
    agent = get_pydantic_agent(model, agent_cfg, phase_id, phase.tools, instrument=instrument)
    deps = AgentDeps(workdir=workdir, cfg=agent_cfg)
    # First user message: the common template rendered for the entry phase.
    first_message = render_user(
        agent_cfg,
        phase_id,
        {"task": prompt, "phase_prompt": load_prompt(f"{phase_id}.md")},
    )
    _log_event(
        "agent_start",
        model=_resolve_model_name(),
        base_url=_required_env("OPENAI_BASE_URL"),
        workdir=str(workdir),
        prompt=prompt,
        temp=agent_cfg.agent.temp,
        soft_time=agent_cfg.budget.soft_time,
        hard_time=agent_cfg.budget.hard_time,
        request_limit=agent_cfg.budget.request_limit,
        token_budget=agent_cfg.budget.token_budget,
    )
    status, output = await _run_main(agent, model, cfg, first_message, deps)
    if status == "budget":
        await _run_commit(agent, model, cfg, deps, prompt)
    model.log_pending_usage()
    _log_event(
        "agent_done",
        status=status,
        elapsed_s=round(model.elapsed(), 1),
        output=output,
    )
    return output


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
