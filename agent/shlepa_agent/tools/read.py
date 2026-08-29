"""Read tool: paged reads of text files (0-based lines, char cap)."""

from __future__ import annotations

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path

DEFAULT_MAX_LIMIT = 100
DEFAULT_MAX_OUTPUT = 4000
_BINARY_PROBE_BYTES = 8192


async def read(
    ctx: "RunContext[AgentDeps]", path: str, offset: int = 0, limit: int = 0
) -> str:
    """Read a text file in pages. offset is the 0-based line to start from;
    limit is how many lines to return (max 100; 0 or omitted = first page of
    100). Output is capped at 4000 characters. The result tells you how many
    lines remain and which offset to continue with."""
    rcfg = ctx.deps.cfg.tools.read
    max_limit = rcfg.max_limit or DEFAULT_MAX_LIMIT
    max_output = rcfg.max_output or DEFAULT_MAX_OUTPUT

    p = resolve_path(path, ctx.deps.workdir)
    _log_event("tool_call", tool="read", path=str(p), offset=offset, limit=limit)

    if not p.exists():
        return f"File not found: {path}"
    if p.is_dir():
        return f"Path is a directory, not a file: {path}"

    try:
        head = p.open("rb").read(_BINARY_PROBE_BYTES)
        if b"\x00" in head:
            return f"Binary file (use bash to inspect): {path}"
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Read error: {e}"

    lines = text.splitlines(keepends=True)
    total = len(lines)
    notes: list[str] = []

    if offset < 0:
        offset = 0
        notes.append("offset clamped to 0")
    if limit < 0:
        limit = 0
    if limit == 0:
        limit = max_limit
    elif limit > max_limit:
        notes.append(f"limit clamped to {max_limit}")
        limit = max_limit

    if offset >= total:
        return (
            f"End of file: {path} has {total} line(s); "
            f"nothing to read from offset {offset}."
        )

    window = lines[offset : offset + limit]
    body = "".join(window)
    truncated = len(body) > max_output
    if truncated:
        body = body[:max_output]
        full_lines = body.count("\n")  # terminated lines only
        continue_at = offset + full_lines
        notes.append(
            f"output truncated to {max_output} chars; "
            f"continue with offset={continue_at}"
        )
    else:
        remaining = total - (offset + len(window))
        if remaining > 0:
            notes.append(
                f"{remaining} more lines; "
                f"continue with offset={offset + len(window)}"
            )

    if notes:
        return body + "\n[" + " | ".join(notes) + "]"
    return body


READ_TOOL = Tool(
    name="read",
    note="read: paged file reads (100 lines per page by default, output capped "
    "at 4000 chars; 0-based offset; the result tells you where to continue).",
    run=read,
)
