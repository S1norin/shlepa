"""append_file tool: append text to a file."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path


def _append_text(file_path: Path, content: str) -> None:
    with file_path.open("a", encoding="utf-8") as f:
        f.write(content)


async def append_file(ctx: "RunContext[AgentDeps]", path: str, content: str) -> str:
    """Append text to a file (no newline added)."""
    workdir = ctx.deps.workdir
    _log_event("tool_call", tool="append_file", path=path, content=content)
    file_path = resolve_path(path, workdir)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(_append_text, file_path, content)
    result = f"Appended {len(content)} chars to {file_path}"
    _log_event("tool_result", tool="append_file", result=result)
    return result


APPEND_FILE_TOOL = Tool(
    name="append_file",
    note="append_file — append text to a file (no newline added)",
    run=append_file,
)
