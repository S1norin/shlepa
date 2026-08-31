"""code_search + file_outline tools (AGENT_CODE_SEARCH, OFF by default).

Tool records over the engine module (``shlepa_agent.code_search``). Off by
default: the ``AGENT_CODE_SEARCH`` env var (values: rg | sifs) enables them
via the config layer (``config._apply_code_search_env``) — with it unset
the agent is byte-identical to the baseline (see
``tests/test_code_search_tools.py``, golden fixture
``tests/fixtures/default_prompt.txt``).

Each call runs the (sync, subprocess-based) engine in a worker thread
under a per-call wall from the config (``tools.code_search.timeout`` /
``tools.file_outline.timeout``, default 30s — the v5 regime bash cap). The
engine's own 60s rg wall is too high for a tool call and is superseded
here; on the wall the tool reports a timeout (the worker thread may finish
in the background, same contract as the file tools). Results are
instrumented with ``format_tool_result`` and carry UNTRUSTED markers (the
search output is environment data).

Shaped for the later named toolset arms (#51): an arm is exactly a config
mutation (engine + enabled flags + phase tool lists), applied once per run
by ``config._apply_code_search_env``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from shlepa_agent import code_search as engine
from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, format_tool_result

if TYPE_CHECKING:
    from pydantic_ai import RunContext

#: Per-call wall fallback when the config does not provide one (the v5
#: regime bash cap).
DEFAULT_WALL_S = 30.0


async def _run_engine(
    ctx: "RunContext[AgentDeps]",
    name: str,
    args: dict,
    body,
    wall: float,
    *,
    note: str | None = None,
) -> str:
    """Run a sync engine body in a worker thread under the per-call wall.

    On the wall the tool reports a compact timeout message (the thread may
    keep running in the background) instead of hanging the run.
    """
    t0 = time.monotonic()
    _log_event("tool_call", tool=name, **args)
    try:
        async with asyncio.timeout(wall):
            result = await asyncio.to_thread(body)
    except TimeoutError:
        result = f"{name}: timed out after {wall:g}s (per-call wall)"
    _log_event("tool_result", tool=name, output=result)
    return format_tool_result(ctx, name, result, t0, args=args, untrusted=True, note=note)


async def code_search(
    ctx: "RunContext[AgentDeps]",
    query: str,
    path: str = ".",
    mode: str = "bm25",
    limit: int = 5,
    max_tokens: int = 1500,
) -> str:
    """Search the codebase for code matching ``query``.

    Returns ranked ``file:line-range`` windows with a few context lines —
    use it to LOCATE code instead of grep/read round trips. ``path`` is the
    directory to search (default: the whole working directory). ``mode``:
    "bm25" (keyword search) or "hybrid" (natural language; needs the
    embedding model, dev only — falls back to bm25 when the model is
    absent; ignored by the rg engine). ``limit`` caps the files/chunks
    shown; ``max_tokens`` caps the result size in tokens.
    """
    cfg = ctx.deps.cfg
    workdir = ctx.deps.workdir
    wall = cfg.tools.code_search.timeout or DEFAULT_WALL_S
    eng = (cfg.code_search.engine or "auto").strip().lower()

    # Engine mapping: rg -> the ripgrep scan; sifs -> bm25, or hybrid when
    # the model asks for it (hybrid without the model degrades inside the
    # engine, with a NOTE line). Any other value: auto resolution.
    if eng == "rg":
        eng_arg = "rg"
        note = (
            "hybrid mode needs the sifs engine (configured: rg); ran rg"
            if mode == "hybrid"
            else None
        )
    elif eng == "sifs" and mode == "hybrid":
        eng_arg = "sifs-hybrid"
        note = None
    else:
        eng_arg = "sifs" if eng == "sifs" else "auto"
        note = None

    def body() -> str:
        return engine.code_search(
            query,
            path,
            limit=limit,
            max_tokens=max_tokens,
            workdir=workdir,
            engine=eng_arg,
        )

    args = {
        "query": query,
        "path": path,
        "mode": mode,
        "limit": limit,
        "max_tokens": max_tokens,
    }
    return await _run_engine(ctx, "code_search", args, body, wall, note=note)


async def file_outline(
    ctx: "RunContext[AgentDeps]",
    path: str,
) -> str:
    """List the def/class/func symbols of one file with line ranges.

    Use it to navigate a file before reading it. ``path`` is the file to
    outline (relative paths resolve against the working directory).
    """
    cfg = ctx.deps.cfg
    workdir = ctx.deps.workdir
    wall = cfg.tools.file_outline.timeout or DEFAULT_WALL_S
    eng = (cfg.code_search.engine or "auto").strip().lower()

    def body() -> str:
        if eng == "rg":
            return engine.file_outline(path, workdir=workdir, engine="regex")
        if eng == "sifs":
            return engine.file_outline(path, workdir=workdir, engine="sifs")
        return engine.file_outline(path, workdir=workdir)  # auto

    return await _run_engine(ctx, "file_outline", {"path": path}, body, wall)


CODE_SEARCH_TOOL = Tool(
    name="code_search",
    note=(
        "code_search: search the codebase, returns ranked file:line windows "
        "with context (query, path=dir, mode=bm25|hybrid, limit, max_tokens). "
        "Locate code in one call instead of grep/read round trips."
    ),
    run=code_search,
)

FILE_OUTLINE_TOOL = Tool(
    name="file_outline",
    note=(
        "file_outline: list def/class/func symbols of one file with line "
        "ranges (path); use it to navigate a file before reading it."
    ),
    run=file_outline,
)
