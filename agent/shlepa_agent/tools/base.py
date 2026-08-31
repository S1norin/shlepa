"""Shared types and result formatting for the modular tool system."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from shlepa_agent.config import AgentConfig

from shlepa_agent.budget import Budget

#: Hard per-call wall-clock cap for the file tools (read/write/edit). The
#: file I/O runs in a worker thread, so a slow/hung read cannot eat the run.
FILE_TOOL_TIMEOUT_S = 5.0

#: Default file size cap (MB) for the read/edit tools.
DEFAULT_MAX_FILE_MB = 100.0


def file_size_error(path: Path, max_mb: float) -> str | None:
    """Failure message if the file is larger than the cap, else None."""
    try:
        size = path.stat().st_size
    except OSError:
        return None  # existence/read errors are reported by the tool itself
    if size <= max_mb * 1024 * 1024:
        return None
    return (
        f"file is {size / (1024 * 1024):.1f} MB, limit is {max_mb:g} MB; "
        "use bash: head/tail/grep/sed -n 'A,Bp'"
    )


async def run_file_tool(body: Callable[[], Awaitable[str]], fail: Callable[[str], str]) -> str:
    """Run a read/write/edit body under the hard per-call timeout (#61).

    On timeout the tool reports ``tool timed out after Ns`` instead of
    hanging the whole run; the worker thread may finish in the background.
    """
    try:
        async with asyncio.timeout(FILE_TOOL_TIMEOUT_S):
            return await body()
    except TimeoutError:
        return fail(f"tool timed out after {FILE_TOOL_TIMEOUT_S:g}s")


@dataclass(frozen=True)
class AgentDeps:
    """Per-run dependencies handed to every tool call via RunContext.deps."""

    workdir: Path
    cfg: "AgentConfig"
    #: Wall-clock elapsed seconds since the run started (same clock as the
    #: global budget, i.e. ``TrackedModel.elapsed``).
    clock: Callable[[], float]
    #: Adaptive per-run budget (derived from the task time limit T). None in
    #: legacy/test contexts — code must fall back to ``cfg.budget`` values.
    budget: "Budget | None" = None


#: Values longer than this in the ``[tool] name(args=...)`` header are cut.
_ARG_REPR_LIMIT = 200


def _short(value: Any) -> str:
    """Compact repr of one tool argument for the result header."""
    s = repr(value)
    if len(s) <= _ARG_REPR_LIMIT:
        return s
    return s[:_ARG_REPR_LIMIT] + "…(truncated)"


def format_tool_result(
    ctx: "RunContext[AgentDeps]",
    name: str,
    body: str,
    started: float,
    *,
    args: Mapping[str, Any] | None = None,
    note: str | None = None,
    failed: str | None = None,
    untrusted: bool = False,
) -> str:
    """Render the instrumented result of a tool call.

    Layout (one result per tool call):

    - header line: ``[tool] name(arg1=..., arg2=...)``
    - timing line: ``spent`` (tool wall time), ``ended_at`` (seconds into the
      run), ``time_left`` (until the global hard-time deadline)
    - optional ``NOTE:`` line (e.g. clamped parameters)
    - optional ``FAILED:`` line (only on tool failure)
    - the tool output: wrapped in ``UNTRUSTED TEXT`` markers when it carries
      environment data (read/bash), plain otherwise (write/edit status)

    ``started`` is the ``time.monotonic()`` value captured at tool entry.
    """
    spent = time.monotonic() - started
    ended = ctx.deps.clock()
    hard = ctx.deps.budget.hard if ctx.deps.budget is not None else ctx.deps.cfg.budget.hard_time
    time_left = max(0.0, hard - ended)
    argstr = ", ".join(f"{k}={_short(v)}" for k, v in (args or {}).items())
    lines = [
        f"[tool] {name}({argstr})",
        f"  spent={spent:.2f}s ended_at={ended:.1f}s time_left={time_left:.1f}s",
    ]
    if note:
        lines.append(f"  NOTE: {note}")
    if failed:
        lines.append(f"  FAILED: {failed}")
    if untrusted:
        lines += [
            "UNTRUSTED TEXT ---------------",
            body or "<empty>",
            "END OF UNTRUSTED TEXT-----------",
        ]
    else:
        lines.append(body)
    return "\n".join(lines)


@dataclass(frozen=True)
class Tool:
    """One agent tool: name, short usage note, async implementation.

    ``run`` has the pydantic-ai tool signature
    ``(ctx: RunContext[AgentDeps], **args) -> str``. Its docstring is the
    tool description sent to the model in the API tool spec; ``note`` is a
    one-line usage hint rendered into the request template's ``tools`` block.
    """

    name: str
    note: str
    run: Callable[..., Any]


def resolve_path(path: str, workdir: Path) -> Path:
    if Path(path).is_absolute():
        return Path(path).resolve()
    return (workdir / path).resolve()
