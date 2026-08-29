"""Bash tool: run a shell command in the working directory."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import AgentDeps, Tool

DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_OUTPUT = 16000


async def bash(ctx: "RunContext[AgentDeps]", command: str) -> str:
    """Run a shell command in the working directory. Killed after 120 seconds.
    Use absolute paths; combine steps with && where sensible."""
    tcfg = ctx.deps.cfg.tools.bash
    timeout = tcfg.timeout if tcfg.timeout is not None else DEFAULT_TIMEOUT
    max_output = tcfg.max_output if tcfg.max_output is not None else DEFAULT_MAX_OUTPUT
    workdir = ctx.deps.workdir
    _log_event("tool_call", tool="bash", command=command, cwd=str(workdir))
    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.TimeoutError):
        timed_out = True
        proc.kill()
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        except Exception:
            stdout, stderr = b"", b""
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")
    if timed_out:
        header = (
            f"$ {command}\n[cwd] {workdir}\n"
            f"[exit_code] 124 (KILLED after {timeout:.0f}s timeout - command was too "
            f"slow or hung)\n"
        )
    else:
        header = f"$ {command}\n[cwd] {workdir}\n[exit_code] {proc.returncode}\n"
    result = _truncate(
        header + f"[stdout]\n{out or '<empty>'}\n[stderr]\n{err or '<empty>'}",
        max_output,
    )
    _log_event(
        "tool_result",
        tool="bash",
        exit_code="timeout" if timed_out else proc.returncode,
        stdout=out or "<empty>",
        stderr=err or "<empty>",
    )
    return result


BASH_TOOL = Tool(
    name="bash",
    note=(
        "bash — run a shell command (killed after the configured timeout); "
        "use absolute paths; start servers with nohup + & then verify"
    ),
    run=bash,
)
