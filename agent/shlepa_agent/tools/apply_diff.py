"""apply_diff tool: apply a unified diff (patch -N) to an existing file."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path


async def apply_diff(ctx: "RunContext[AgentDeps]", path: str, diff_content: str) -> str:
    """Apply a unified diff (patch -N) to an existing file."""
    workdir = ctx.deps.workdir
    _log_event("tool_call", tool="apply_diff", path=path, diff=diff_content)
    file_path = resolve_path(path, workdir)
    if not file_path.exists():
        result = f"File not found: {file_path}"
        _log_event("tool_result", tool="apply_diff", result=result)
        return result
    if not file_path.is_file():
        result = f"Not a file: {file_path}"
        _log_event("tool_result", tool="apply_diff", result=result)
        return result
    _log_event("tool_call", tool="patch", path=str(file_path))
    proc = await asyncio.create_subprocess_exec(
        "patch",
        "-N",
        "-r",
        "-",
        str(file_path),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(diff_content.encode())
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    output = (
        f"[exit_code] {proc.returncode}\n"
        f"[stdout]\n{out or '<empty>'}\n"
        f"[stderr]\n{err or '<empty>'}"
    )
    if proc.returncode != 0:
        result = f"Failed to apply diff to {file_path}.\n{output}"
    else:
        result = f"Applied diff to {file_path}.\n{output}"
    _log_event("tool_result", tool="apply_diff", exit_code=proc.returncode, result=result)
    return result


APPLY_DIFF_TOOL = Tool(
    name="apply_diff",
    note="apply_diff — apply a unified diff (patch -N) to an existing file",
    run=apply_diff,
)
