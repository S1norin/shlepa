"""mitre_kb tool (OFF by default; the +mitre-kb toolset arm enables it).

Tool record over the engine module (``shlepa_agent.mitre_kb``). Off by
default: the ``AGENT_TOOLSET=+mitre-kb`` arm enables it via
``config._enable_mitre_kb_tools`` (the same mutation shape as
``_enable_forensics_tools``) — with no arm set the agent stays
byte-identical to the baseline (golden fixture
``tests/fixtures/default_prompt.txt``).

Read-only by construction: the engine only opens KB files in read mode.
The KB content is pinned static reference data, so results are not
wrapped in UNTRUSTED markers (unlike read/bash environment data). The
char cap comes from ``tools.mitre_kb.max_output`` in config.
"""

from __future__ import annotations

import asyncio
import time

from pydantic_ai import RunContext

from shlepa_agent import mitre_kb as engine
from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, format_tool_result

#: Per-call wall fallback when the config does not provide one (the v5
#: regime bash cap). The in-memory search is sub-millisecond; this is a
#: safety net only.
DEFAULT_WALL_S = 30.0


async def mitre_kb(
    ctx: "RunContext[AgentDeps]",
    query: str,
    full: bool = False,
) -> str:
    """Search the pinned MITRE ATT&CK knowledge base (709 techniques).

    Pass a technique id (e.g. "T1003.003"; old renumbered ids like
    "T1562.001" resolve via the alias map) or free-text keywords from the
    observed evidence (tools, paths, API names, ports). Returns the top-5
    matching techniques, each with a 1-3 line cheat sheet. Set full=true
    for the verbatim ATT&CK descriptions (higher fidelity, more tokens).
    Read-only; use it to confirm technique ids before reporting them.
    """
    cfg = ctx.deps.cfg
    wall = cfg.tools.mitre_kb.timeout or DEFAULT_WALL_S
    max_output = cfg.tools.mitre_kb.max_output or engine.DEFAULT_MAX_OUTPUT
    args = {"query": query, "full": full}
    t0 = time.monotonic()
    _log_event("tool_call", tool="mitre_kb", **args)

    def body() -> str:
        kb = engine.get_kb()
        mode, hits, unknown = kb.search(query)
        return kb.render(mode, hits, unknown, full=full, max_output=max_output)

    try:
        async with asyncio.timeout(wall):
            result = await asyncio.to_thread(body)
    except TimeoutError:
        result = f"mitre_kb: timed out after {wall:g}s (per-call wall)"
    _log_event("tool_result", tool="mitre_kb", output=result)
    return format_tool_result(ctx, "mitre_kb", result, t0, args=args)


MITRE_KB_TOOL = Tool(
    # function name == model-facing tool name (pydantic-ai default)
    name="mitre_kb",
    note=(
        "mitre_kb: search the pinned MITRE ATT&CK v19.2 KB (709 techniques): "
        "pass a T-ID (old aliases resolve) or evidence keywords; returns top-5 "
        "cheat-sheet rows, full=true gives verbatim ATT&CK descriptions. "
        "Confirm technique ids with it before reporting them."
    ),
    run=mitre_kb,
)
