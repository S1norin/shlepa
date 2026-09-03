"""Recon tool: thin wrapper around the bundled zero-dependency recon script.

The script (``tools/recon.py``) is deterministic, stateless, and read-only
by construction (only file reads; no writes, no subprocesses — verified in
docs/plans/agent-v6-pipeline-hardening.md). This tool adds:

- mode wiring (url / code / data) so the model does not have to remember
  the script's CLI,
- a hard per-call wall cap (the script's own crawl budget is longer; the
  cap must fit the PLAN phase),
- an output cap with a truncation marker (the script self-caps to 8192
  bytes; this is the belt-and-braces backstop the digest and the context
  budget rely on).
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event, _truncate
from shlepa_agent.tools.base import (
    AgentDeps,
    Tool,
    finalizing_result,
    format_tool_result,
)

#: Hard per-call wall cap for the recon script.
RECON_TIMEOUT_S = 25.0

#: Hard char cap on the result body (8 KB — the script's own cap).
DEFAULT_MAX_OUTPUT = 8192

#: Script self-caps to 8192 bytes; anything beyond is a contract violation
#: and gets cut with a marker rather than trusted.
_MAX_SCRIPT_OUTPUT = 8192

_CHUNK = 64 * 1024


def _candidate_scripts() -> list[Path]:
    """Where the bundled script can live, in priority order.

    - ``tools/recon.py`` in the working directory (submission layout: the
      zip root is the cwd and bundles ``tools/``);
    - next to the agent package (repo layout and the staged ``/agent/``
      dev-image layout both put the package and ``tools/`` as siblings);
    - the fixed dev-image path (fallback the system prompt documents).
    """
    pkg_root = Path(__file__).resolve().parents[2]  # .../agent
    return [
        Path.cwd() / "tools" / "recon.py",
        pkg_root / "tools" / "recon.py",
        Path("/agent/tools/recon.py"),
    ]


def find_recon_script() -> Path | None:
    for cand in _candidate_scripts():
        if cand.is_file():
            return cand
    return None


def _script_args(mode: str, target: str) -> list[str]:
    if mode == "url":
        return [target]
    if mode in ("code", "data"):
        return ["--" + mode, target]
    raise ValueError(f"unknown recon mode: {mode!r} (use url, code or data)")


async def _read_bounded(stream, cap: int) -> bytes:
    """Read a stream up to ``cap`` bytes, then drain the rest (bounded
    retention: keep reading so the pipe cannot block the script)."""
    kept = bytearray()
    while True:
        chunk = await stream.read(_CHUNK)
        if not chunk:
            return bytes(kept)
        if len(kept) < cap:
            kept += chunk[: cap - len(kept)]
        # beyond the cap: discard (still draining the pipe)


async def recon(
    ctx: "RunContext[AgentDeps]", mode: str = "code", target: str = "."
) -> str:
    """Run the bundled deterministic recon script and return its compact
    JSON surface map. Read-only by construction — it maps a surface, it
    never writes. Modes: "url" (live local web target: recon <url>),
    "code" (source tree: map sinks and entry points), "data" (evidence dir:
    flags, secrets, encoded blobs). Output is capped at 8192 chars; the
    call is killed at 25 s (a url crawl may be cut short — fall back to
    targeted reads/search for what it missed)."""
    t0 = time.monotonic()
    # w3-2: inside the finalization reserve recon is not executed.
    blocked = finalizing_result(
        ctx, "recon", t0, args={"mode": mode, "target": target}
    )
    if blocked is not None:
        return blocked
    rcfg = ctx.deps.cfg.tools.recon
    max_output = rcfg.max_output or DEFAULT_MAX_OUTPUT
    _log_event("tool_call", tool="recon", mode=mode, target=target)

    def finish(
        body: str, *, note: str | None = None, failed: str | None = None
    ) -> str:
        return format_tool_result(
            ctx, "recon", body, t0, args={"mode": mode, "target": target},
            note=note, failed=failed, untrusted=True,
        )

    try:
        args = _script_args(mode, target)
    except ValueError as e:
        return finish("", failed=str(e))

    script = find_recon_script()
    if script is None:
        return finish("", failed="recon script tools/recon.py not found in this environment")

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", str(script), *args,
            cwd=str(ctx.deps.workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as e:
        return finish("", failed=f"spawn error: {e}")

    timed_out = False
    try:
        out_task = asyncio.create_task(_read_bounded(proc.stdout, _MAX_SCRIPT_OUTPUT))
        err_task = asyncio.create_task(_read_bounded(proc.stderr, 4096))
        await asyncio.wait_for(proc.wait(), timeout=RECON_TIMEOUT_S)
        out, err = await out_task, await err_task
    except TimeoutError:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass  # group already gone
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except TimeoutError:
            pass  # SIGKILLed; a stuck reap must not eat the run
        # The bounded readers are still pending on the now-dead pipes;
        # cancel them so the loop closes clean.
        for task in (out_task, err_task):
            task.cancel()
        out, err = b"", b""

    if timed_out:
        _log_event("tool_result", tool="recon", mode=mode, exit_code="timeout")
        return finish(
            "",
            note=f"script killed after {RECON_TIMEOUT_S:.0f}s",
            failed=(
                f"recon timed out after {RECON_TIMEOUT_S:.0f}s — the surface is "
                "too big for one pass; confirm specifics with targeted read/search "
                "instead"
            ),
        )

    body = out.decode("utf-8", errors="replace")
    if not body.strip():
        errtext = err.decode("utf-8", errors="replace").strip()
        _log_event("tool_result", tool="recon", mode=mode,
                   exit_code=proc.returncode, error=errtext or "<empty>")
        return finish(
            "",
            failed=(
                f"recon exited {proc.returncode} with no output"
                + (f": {errtext[:400]}" if errtext else "")
            ),
        )

    truncated = False
    if len(body) > _MAX_SCRIPT_OUTPUT:
        body = body[:_MAX_SCRIPT_OUTPUT]
        truncated = True
    body = _truncate(body, max_output)
    _log_event("tool_result", tool="recon", mode=mode,
               exit_code=proc.returncode, output=body)
    note = None
    if truncated:
        note = f"output cut to {_MAX_SCRIPT_OUTPUT} chars (script exceeded its cap)"
    return finish(body, note=note)


RECON_TOOL = Tool(
    name="recon",
    note=(
        "recon: deterministic read-only surface map (bundled zero-dependency "
        "script). mode='url' for a live local target, mode='code' for a "
        "source tree, mode='data' for an evidence dir; target is the URL or "
        "path. Returns flat JSON <=8192 chars; hard 25s cap (a url crawl may "
        "time out — confirm specifics with read/search)."
    ),
    run=recon,
)
