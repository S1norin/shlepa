"""write_file tool: write exact content to a file."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path


async def write_file(ctx: "RunContext[AgentDeps]", path: str, content: str) -> str:
    """Write EXACT content to a file (creates parent dirs, overwrites).
    No trailing newline is added. Use this for final deliverables."""
    workdir = ctx.deps.workdir
    _log_event("tool_call", tool="write_file", path=path, content=content)
    file_path = resolve_path(path, workdir)
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(file_path.write_text, content, encoding="utf-8")
    except Exception as e:
        result = f"Failed to write {file_path}: {e}"
        _log_event("tool_result", tool="write_file", result=result)
        return result
    result = f"Wrote exactly {len(content)} chars to {file_path}"
    _log_event("tool_result", tool="write_file", path=str(file_path), result=result)
    return result


WRITE_FILE_TOOL = Tool(
    name="write_file",
    note=(
        "write_file — write exact full content (creates parent dirs, no trailing newline); "
        "use for final deliverables"
    ),
    run=write_file,
)
