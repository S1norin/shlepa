"""recon tool (OFF by default; the +recon toolset arm enables it).

Tool record over the engine module (``shlepa_agent.recon``). Off by
default: the ``AGENT_TOOLSET=+recon`` arm enables it (same mutation shape
as ``_enable_forensics_tools``) — with no arm set the agent stays
byte-identical to the baseline (golden fixture
``tests/fixtures/default_prompt.txt``).

Read-only by construction: the engine only does HTTP GET, port probes and
file reads (see ``shlepa_agent.recon``). The per-call wall defaults to 30s
(the v5 regime bash cap; ``tools.recon.timeout`` in config) and is enforced
around a worker thread — a hung scan cannot eat the run. The web engine
also has its own 25s internal deadline, so the wall mainly binds on large
code/data scans (which have no internal deadline). On timeout the result
is a fail-safe note, never an exception. Results carry UNTRUSTED markers
(environment data).
"""

from __future__ import annotations

import asyncio
import time
from typing import Literal

from pydantic_ai import RunContext

from shlepa_agent import recon as engine
from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, format_tool_result, resolve_path

#: Per-call wall fallback when the config does not provide one (the v5
#: regime bash cap).
DEFAULT_WALL_S = 30.0


def _run_engine(mode: str, target: str, workdir) -> str:
    """One engine call, fail-safe: engine exceptions become error notes.

    ``workdir`` resolves relative code/data targets (the web mode takes the
    URL verbatim).
    """
    try:
        if mode == "web":
            out = engine.recon_web(target)
        elif mode == "code":
            out = engine.recon_code(resolve_path(target, workdir))
        else:
            out = engine.recon_data(resolve_path(target, workdir))
    except Exception as e:  # fail-safe: a broken engine call is data, not a crash
        out = {"error": engine.err_note(e)}
    return engine.render(out)


async def recon(
    ctx: "RunContext[AgentDeps]",
    mode: Literal["web", "code", "data"],
    target: str,
) -> str:
    """Deterministic attack-surface recon (stdlib engine, no LLM, no writes).

    Pick the mode that matches the target kind:

    - mode="web": target = http(s) URL. Returns open ports, vhosts, an
      endpoint inventory (forms, params), sensitive-file hits and error
      excerpts, plus a 404 baseline.
    - mode="code": target = a source-code directory. Returns entry points,
      risky sinks (eval/exec/injection/paths) and docker-compose services
      and ports.
    - mode="data": target = an evidence/log directory. Returns file
      inventory, formats, time ranges and IOC-shaped needles (flags, hex,
      base64, key=value).

    The JSON is compact (<=8KB); on a slow web target the stages past the
    internal ~25s deadline come back as "skipped (deadline)". Use it FIRST
    for web/code/evidence recon — before grep/read round trips — then
    follow up with targeted reads on what it points at.
    """
    cfg = ctx.deps.cfg
    workdir = ctx.deps.workdir
    wall = cfg.tools.recon.timeout or DEFAULT_WALL_S
    args = {"mode": mode, "target": target}
    t0 = time.monotonic()
    _log_event("tool_call", tool="recon", **args)

    try:
        async with asyncio.timeout(wall):
            result = await asyncio.to_thread(_run_engine, mode, target, workdir)
    except TimeoutError:
        result = f"recon: timed out after {wall:g}s (per-call wall)"
    note = None
    cap = cfg.tools.recon.max_output
    if cap and len(result) > cap:
        result = result[:cap]
        note = f"truncated to {cap} chars (tools.recon.max_output)"
    _log_event("tool_result", tool="recon", output=result)
    return format_tool_result(
        ctx, "recon", result, t0, args=args, untrusted=True, note=note
    )


RECON_TOOL = Tool(
    # function name == model-facing tool name (pydantic-ai default)
    name="recon",
    note=(
        "recon: deterministic read-only attack-surface recon; mode 'web' "
        "(http(s) URL), 'code' (source dir), 'data' (evidence/log dir). "
        "Call it FIRST on web/code/evidence recon before grep/read round "
        "trips; ~25s cap, stages past it are marked 'skipped (deadline)'."
    ),
    run=recon,
)
