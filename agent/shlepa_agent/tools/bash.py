"""Bash tool: run a shell command with a per-call timeout (clamped, announced)."""

from __future__ import annotations

import asyncio
import time

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import AgentDeps, Tool, format_tool_result

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_TIMEOUT = 120.0
DEFAULT_MAX_OUTPUT = 16000
MIN_TIMEOUT = 1.0


async def bash(
    ctx: "RunContext[AgentDeps]", command: str, timeout: float | None = None
) -> str:
    """Run a shell command in the working directory. ``timeout`` is the
    per-call limit in seconds (default 30, max 30 — the fixed regime bash
    cap; out-of-range values are clamped and reported). Use absolute paths;
    combine steps with && where sensible. Start servers with nohup + &
    then verify they respond."""
    t0 = time.monotonic()
    tcfg = ctx.deps.cfg.tools.bash
    max_timeout = tcfg.max_timeout or DEFAULT_MAX_TIMEOUT
    max_output = tcfg.max_output or DEFAULT_MAX_OUTPUT
    default = tcfg.timeout if tcfg.timeout is not None else DEFAULT_TIMEOUT
    workdir = ctx.deps.workdir
    _log_event(
        "tool_call", tool="bash", command=command, cwd=str(workdir), timeout=timeout
    )
    args = {"command": command}
    if timeout is not None:
        args["timeout"] = timeout

    def finish(body: str, *, note: str | None = None, failed: str | None = None) -> str:
        return format_tool_result(
            ctx, "bash", body, t0, args=args, note=note, failed=failed, untrusted=True
        )

    note = ""
    t = default if timeout is None else float(timeout)
    if t > max_timeout:
        note = f"timeout clamped to {max_timeout:.0f}s (max)"
        t = max_timeout
    elif t < MIN_TIMEOUT:
        note = f"timeout clamped to {MIN_TIMEOUT:.0f}s (min)"
        t = MIN_TIMEOUT

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        return finish("", note=note or None, failed=f"spawn error: {e}")

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
            f"$ {command}\n[cwd] {workdir}\n"
            f"[exit_code] 124 (KILLED after {t:.0f}s timeout - command was too "
            f"slow or hung)\n"
        )
    else:
        header = f"$ {command}\n[cwd] {workdir}\n[exit_code] {proc.returncode}\n"
    body = _truncate(
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
    if timed_out:
        return finish(
            body,
            note=note or None,
            failed=f"command killed after {t:.0f}s timeout (exit 124)",
        )
    return finish(body, note=note or None)


BASH_TOOL = Tool(
    name="bash",
    note=(
        "bash: run a shell command in the working directory. Per-call timeout "
        "in seconds (default 30, max 120); use absolute paths; start servers "
        "with nohup + & and verify they respond."
    ),
    run=bash,
)
