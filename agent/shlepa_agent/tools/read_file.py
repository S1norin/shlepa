"""read_file tool: read a text file from the working directory."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path

DEFAULT_MAX_OUTPUT = 16000


async def read_file(ctx: "RunContext[AgentDeps]", path: str) -> str:
    """Read a text file (truncated to a limit). For long files use bash: head/tail/sed -n."""
    tcfg = ctx.deps.cfg.tools.read_file
    max_chars = tcfg.max_output if tcfg.max_output is not None else DEFAULT_MAX_OUTPUT
    workdir = ctx.deps.workdir
    _log_event("tool_call", tool="read_file", path=path)
    file_path = resolve_path(path, workdir)
    if not file_path.exists():
        result = f"File not found: {file_path}"
        _log_event("tool_result", tool="read_file", result=result)
        return result
    if not file_path.is_file():
        result = f"Not a file: {file_path}"
        _log_event("tool_result", tool="read_file", result=result)
        return result
    result = _truncate(await asyncio.to_thread(file_path.read_text, encoding="utf-8"), max_chars)
    _log_event("tool_result", tool="read_file", path=path, result=result)
    return result


READ_FILE_TOOL = Tool(
    name="read_file",
    note=(
        "read_file — read a text file (truncated to the configured limit); "
        "for long files use bash head/tail/sed -n"
    ),
    run=read_file,
)
