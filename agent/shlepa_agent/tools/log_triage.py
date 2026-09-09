"""log_triage tool (baseline, read-only).

Tool record over the engine module (``shlepa_agent.log_triage``). Baseline
in the v6-rewrite: the ``[tool_policy]`` phase matrix routes it to the
read-only PLAN phase and the WORK phase alike (disable for A/B with
``SHLEPA_LOG_TRIAGE=0``).

Read-only by construction: the engine only opens files in read mode (see
``shlepa_agent.log_triage``). The per-call wall defaults to 30s (the regime
bash cap; ``tools.log_triage.timeout`` in config). Inside the finalization
reserve (w3-2) the call is not executed (exploratory tool). Results carry
UNTRUSTED markers (file content is environment data).
"""

from __future__ import annotations

import asyncio
import time

from pydantic_ai import RunContext

from shlepa_agent import log_triage as engine
from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import (
    AgentDeps,
    Tool,
    finalizing_result,
    format_tool_result,
)

#: Per-call wall fallback when the config does not provide one (the v5
#: regime bash cap).
DEFAULT_WALL_S = 30.0


async def log_triage(
    ctx: "RunContext[AgentDeps]",
    path: str = ".",
) -> str:
    """Deterministic read-only triage of log/evidence files.

    Pass a file, a directory of evidence, or "." for the working directory.
    Returns a compact summary per file: record count, time range, top
    entities (events/users/hosts/processes or top tokens), external IPs,
    log levels, rare single-occurrence values (IOC candidates) and the
    peak hour. Use it FIRST on forensics/log tasks, before grep/read round
    trips; then verify specific lines with read/bash.
    """
    cfg = ctx.deps.cfg
    workdir = ctx.deps.workdir
    wall = cfg.tools.log_triage.timeout or DEFAULT_WALL_S
    args = {"path": path}
    t0 = time.monotonic()
    # w3-2: inside the finalization reserve the call is not executed.
    blocked = finalizing_result(ctx, "log_triage", t0, args=args)
    if blocked is not None:
        return blocked
    _log_event("tool_call", tool="log_triage", **args)

    def body() -> str:
        return engine.log_triage(
            path,
            workdir=workdir,
            max_output=cfg.tools.log_triage.max_output or engine.DEFAULT_MAX_OUTPUT,
        )

    try:
        async with asyncio.timeout(wall):
            result = await asyncio.to_thread(body)
    except TimeoutError:
        result = f"log_triage: timed out after {wall:g}s (per-call wall)"
    _log_event("tool_result", tool="log_triage", output=result)
    return format_tool_result(ctx, "log_triage", result, t0, args=args, untrusted=True)


LOG_TRIAGE_TOOL = Tool(
    # function name == model-facing tool name (pydantic-ai default)
    name="log_triage",
    note=(
        "log_triage: deterministic read-only triage of log/evidence files "
        "(path=file, dir, or '.'): record counts, time range, top entities "
        "(events/users/hosts/ips/tokens), rare single-occurrence IOC "
        "candidates, peak hour. Call it FIRST on forensics/log tasks before "
        "grep/read round trips."
    ),
    run=log_triage,
)
