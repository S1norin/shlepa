"""Bash tool: run a shell command with a per-call timeout (clamped, announced)."""

from __future__ import annotations

import asyncio
import os
import signal
import time

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import (
    AgentDeps,
    Tool,
    finalizing_result,
    format_tool_result,
)

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_TIMEOUT = 30.0
DEFAULT_MAX_OUTPUT = 16000
MIN_TIMEOUT = 1.0
_CHUNK = 64 * 1024


class _BoundedRetainer:
    """Head+tail retention for one stream.

    Keeps the first and last ``keep // 2`` bytes of whatever the process
    writes and replaces the middle with a ``[...N bytes dropped...]``
    marker, so an unbounded ``yes``/``dd`` cannot blow up memory or the
    result.
    """

    def __init__(self, keep: int) -> None:
        self._head_cap = max(1, keep // 4)
        self._tail_cap = max(1, keep // 4)
        self._head = bytearray()
        self._tail = bytearray()
        self._dropped = 0

    def add(self, chunk: bytes) -> None:
        rest = chunk
        if len(self._head) < self._head_cap:
            room = self._head_cap - len(self._head)
            self._head += rest[:room]
            rest = rest[room:]
        self._tail += rest
        if len(self._tail) > self._tail_cap:
            overflow = len(self._tail) - self._tail_cap
            del self._tail[:overflow]
            self._dropped += overflow

    def data(self) -> bytes:
        if self._dropped == 0:
            return bytes(self._head) + bytes(self._tail)
        marker = f"\n[...{self._dropped} bytes dropped...]\n".encode("ascii")
        return bytes(self._head) + marker + bytes(self._tail)


async def _read_stream(stream, retainer: _BoundedRetainer) -> None:
    while True:
        chunk = await stream.read(_CHUNK)
        if not chunk:
            return
        retainer.add(chunk)


async def _drain_and_wait(proc, out_ret: _BoundedRetainer, err_ret: _BoundedRetainer) -> None:
    """Drain both pipes (bounded retention), then wait for the process to
    exit — the same contract as ``communicate()``, which awaited
    ``wait()`` after the pipes closed."""
    await asyncio.gather(
        _read_stream(proc.stdout, out_ret),
        _read_stream(proc.stderr, err_ret),
    )
    await proc.wait()


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the command's whole session. The shell runs in its own session
    (start_new_session), so its pgid is its pid: backgrounded children —
    including orphans that outlive the shell and hold our pipes — die with
    it. Must not check proc.returncode first: a child that inherited the
    pipes keeps the group (and the drain timeout) alive even after the
    shell has exited."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass  # group already gone


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

    # w3-2: inside the finalization reserve bash is not executed.
    blocked = finalizing_result(ctx, "bash", t0, args=args)
    if blocked is not None:
        return blocked

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
            start_new_session=True,
        )
    except OSError as e:
        return finish("", note=note or None, failed=f"spawn error: {e}")

    # Bounded retention: each stream keeps head+tail up to half the result
    # cap, so even an unbounded producer stays within the memory/result
    # budget while we drain it.
    keep = max(1024, max_output // 2)
    out_ret = _BoundedRetainer(keep)
    err_ret = _BoundedRetainer(keep)
    timed_out = False
    try:
        await asyncio.wait_for(_drain_and_wait(proc, out_ret, err_ret), timeout=t)
    except TimeoutError:
        timed_out = True
        _kill_process_group(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            pass  # SIGKILLed; a stuck reap must not eat the run
        try:
            proc._transport.close()  # private: avoid GC on a closed loop
        except Exception:
            pass
    out = out_ret.data().decode("utf-8", errors="replace")
    err = err_ret.data().decode("utf-8", errors="replace")
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
        "in seconds (default 30, max 30); use absolute paths; start servers "
        "with nohup + & and verify they respond."
    ),
    run=bash,
)
