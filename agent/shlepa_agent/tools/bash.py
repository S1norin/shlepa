"""Bash tool: run a shell command with a per-call timeout (clamped, announced)."""

from __future__ import annotations

import asyncio

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import AgentDeps, Tool

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_TIMEOUT = 120.0
DEFAULT_MAX_OUTPUT = 16000
MIN_TIMEOUT = 1.0


async def bash(
    ctx: "RunContext[AgentDeps]", command: str, timeout: float | None = None
) -> str:
    """Run a shell command in the working directory. ``timeout`` is the
    per-call limit in seconds (default 30, max 120; out-of-range values are
    clamped and reported). Use absolute paths; combine steps with && where
    sensible. Start servers with nohup + & then verify they respond."""
    tcfg = ctx.deps.cfg.tools.bash
    max_timeout = tcfg.max_timeout or DEFAULT_MAX_TIMEOUT
    max_output = tcfg.max_output or DEFAULT_MAX_OUTPUT
    default = tcfg.timeout if tcfg.timeout is not None else DEFAULT_TIMEOUT
    workdir = ctx.deps.workdir
    _log_event(
        "tool_call", tool="bash", command=command, cwd=str(workdir), timeout=timeout
    )

    note = ""
    t = default if timeout is None else float(timeout)
    if t > max_timeout:
        note = f"[timeout clamped to {max_timeout:.0f}s (max)]\n"
        t = max_timeout
    elif t < MIN_TIMEOUT:
        note = f"[timeout clamped to {MIN_TIMEOUT:.0f}s (min)]\n"
        t = MIN_TIMEOUT

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=t)
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
            note
            + f"$ {command}\n[cwd] {workdir}\n"
            f"[exit_code] 124 (KILLED after {t:.0f}s timeout - command was too "
            f"slow or hung)\n"
        )
    else:
        header = note + f"$ {command}\n[cwd] {workdir}\n[exit_code] {proc.returncode}\n"
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
        "bash — run a shell command (per-call timeout in seconds, default 30, "
        "max 120); use absolute paths; start servers with nohup + & then verify"
    ),
    run=bash,
)
