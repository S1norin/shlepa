"""Shared types and result formatting for the modular tool system."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from shlepa_agent.config import AgentConfig


@dataclass(frozen=True)
class AgentDeps:
    """Per-run dependencies handed to every tool call via RunContext.deps."""

    workdir: Path
    cfg: "AgentConfig"
    #: Wall-clock elapsed seconds since the run started (the
    #: ``TrackedModel.elapsed`` clock).
    clock: Callable[[], float]


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
    - timing line: ``spent`` (tool wall time), ``ended_at`` (seconds into
      the run)
    - optional ``NOTE:`` line (e.g. clamped parameters)
    - optional ``FAILED:`` line (only on tool failure)
    - the tool output: wrapped in ``UNTRUSTED TEXT`` markers when it carries
      environment data (read/bash), plain otherwise (write/edit status)

    ``started`` is the ``time.monotonic()`` value captured at tool entry.
    """
    spent = time.monotonic() - started
    ended = ctx.deps.clock()
    argstr = ", ".join(f"{k}={_short(v)}" for k, v in (args or {}).items())
    lines = [
        f"[tool] {name}({argstr})",
        f"  spent={spent:.2f}s ended_at={ended:.1f}s",
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
