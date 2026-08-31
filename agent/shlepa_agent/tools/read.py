"""Read tool: paged reads of text files (0-based lines, char cap)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import (
    DEFAULT_MAX_FILE_MB,
    AgentDeps,
    Tool,
    file_size_error,
    format_tool_result,
    resolve_path,
    run_file_tool,
)

DEFAULT_MAX_LIMIT = 100
DEFAULT_MAX_OUTPUT = 4000
_BINARY_PROBE_BYTES = 8192


def _load_text(p: Path, path: str) -> str:
    """Binary probe + full load; runs in a worker thread (see run_file_tool)."""
    with p.open("rb") as fh:
        head = fh.read(_BINARY_PROBE_BYTES)
    if b"\x00" in head:
        raise ValueError(f"Binary file (use bash to inspect): {path}")
    return p.read_text(encoding="utf-8", errors="replace")


async def read(
    ctx: "RunContext[AgentDeps]", path: str, offset: int = 0, limit: int = 0
) -> str:
    """Read a text file in pages. offset is the 0-based line to start from;
    limit is how many lines to return (max 100; 0 or omitted = first page of
    100). Output is capped at 4000 characters. Files larger than the
    configured size cap are rejected (use bash head/tail/grep/sed). The
    result tells you how many lines remain and which offset to continue
    with."""
    t0 = time.monotonic()
    rcfg = ctx.deps.cfg.tools.read
    max_limit = rcfg.max_limit or DEFAULT_MAX_LIMIT
    max_output = rcfg.max_output or DEFAULT_MAX_OUTPUT
    max_file_mb = rcfg.max_file_mb or DEFAULT_MAX_FILE_MB

    p = resolve_path(path, ctx.deps.workdir)
    _log_event("tool_call", tool="read", path=str(p), offset=offset, limit=limit)

    def fail(reason: str) -> str:
        return format_tool_result(
            ctx, "read", "", t0, args={"path": path, "offset": offset, "limit": limit},
            failed=reason, untrusted=True,
        )

    async def body(offset: int = offset, limit: int = limit) -> str:
        if not p.exists():
            return fail(f"File not found: {path}")
        if p.is_dir():
            return fail(f"Path is a directory, not a file: {path}")
        size_err = file_size_error(p, max_file_mb)
        if size_err is not None:
            return fail(size_err)
        try:
            text = await asyncio.to_thread(_load_text, p, path)
        except ValueError as e:
            return fail(str(e))
        except OSError as e:
            return fail(f"Read error: {e}")

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
            return fail(
                f"End of file: {path} has {total} line(s); "
                f"nothing to read from offset {offset}."
            )

        end = offset + limit
        window = lines[offset:end]
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

        return format_tool_result(
            ctx, "read", body, t0,
            args={"path": path, "offset": offset, "limit": limit},
            note=" | ".join(notes) or None, untrusted=True,
        )

    return await run_file_tool(body, fail)


READ_TOOL = Tool(
    name="read",
    note="read: read a text file page by page. 0-based offset; 100 lines per "
    "page by default; output capped at 4000 chars; files above the size cap "
    "are rejected (use bash head/tail/grep); the result reports the offset "
    "to continue from.",
    run=read,
)
