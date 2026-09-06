"""Shared types and result formatting for the modular tool system."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Mapping

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from shlepa_agent.config import AgentConfig

#: Hard per-call wall-clock cap for the file tools (read/write/edit). The
#: file I/O runs in a worker thread, so a slow/hung read cannot eat the run.
FILE_TOOL_TIMEOUT_S = 5.0

#: Default file size cap (MB) for the read/edit tools.
DEFAULT_MAX_FILE_MB = 100.0


def file_size_error(path: Path, max_mb: float) -> str | None:
    """Failure message if the file is larger than the cap, else None."""
    try:
        size = path.stat().st_size
    except OSError:
        return None  # existence/read errors are reported by the tool itself
    if size <= max_mb * 1024 * 1024:
        return None
    return (
        f"file is {size / (1024 * 1024):.1f} MB, limit is {max_mb:g} MB; "
        "use bash: head/tail/grep/sed -n 'A,Bp'"
    )


async def run_file_tool(body: Callable[[], Awaitable[str]], fail: Callable[[str], str]) -> str:
    """Run a read/write/edit body under the hard per-call timeout (#61).

    On timeout the tool reports ``tool timed out after Ns`` instead of
    hanging the whole run; the worker thread may finish in the background.
    """
    try:
        async with asyncio.timeout(FILE_TOOL_TIMEOUT_S):
            return await body()
    except TimeoutError:
        return fail(f"tool timed out after {FILE_TOOL_TIMEOUT_S:g}s")


@dataclass
class RepairScope:
    """Mutation budget for the REPAIR phase (w2-5), held by the edit tool.

    Only the deliverable path may be mutated, at most once per repair:
    every other edit call is rejected by the tool itself (harness-side,
    not prompt-side).
    """

    path: Path
    mutations_used: int = 0


@dataclass
class PhaseWindow:
    """The current phase's wall-clock window (w3-2 finalization reserve).

    ``start`` is ``time.monotonic()`` at phase entry; the reserve starts
    when ``cap - (now - start)`` drops below ``finalize_reserve()``.
    """

    phase_id: str
    cap: float
    start: float


@dataclass(frozen=True)
class AgentDeps:
    """Per-run dependencies handed to every tool call via RunContext.deps."""

    workdir: Path
    cfg: "AgentConfig"
    #: Wall-clock elapsed seconds since the run started (the
    #: ``TrackedModel.elapsed`` clock).
    clock: Callable[[], float]
    #: Set while the REPAIR phase runs (w2-5); the edit tool enforces the
    #: artifact-only, one-mutation budget. None outside REPAIR.
    repair_scope: RepairScope | None = field(default=None)
    #: Failure ledger (w3-3): canonical fingerprint -> occurrence count.
    #: Repeated identical failed tool calls are compressed in the result
    #: forwarded to the model (the 1st occurrence is never compressed).
    ledger: dict[str, int] = field(default_factory=dict)
    #: The current phase window (w3-2); None outside a phase (the
    #: finalization reserve guard is then inert).
    phase_window: PhaseWindow | None = field(default=None)
    #: Stagnation tracker (w3-4, shadow-only): {"phase_id", "seq"} of
    #: recent failure keys within the current phase.
    stagnation: dict = field(default_factory=dict)


#: Values longer than this in the ``[tool] name(args=...)`` header are cut.
_ARG_REPR_LIMIT = 200


def _short(value: Any) -> str:
    """Compact repr of one tool argument for the result header."""
    s = repr(value)
    if len(s) <= _ARG_REPR_LIMIT:
        return s
    return s[:_ARG_REPR_LIMIT] + "…(truncated)"


def _ledger_compress(
    deps: "AgentDeps",
    name: str,
    args: Mapping[str, Any] | None,
    body: str,
    failed: str,
) -> tuple[str, int]:
    """w3-3: count this failure in the run ledger; from the 2nd identical
    occurrence return a compact one-liner instead of the full body.

    Returns (body_to_forward, count) — count 0 means "forward as usual"
    (knob off or 1st occurrence, which is recorded but never compressed).
    """
    from shlepa_agent.state import (
        canonical_failure_key,
        extract_exit_code,
        ledger_enabled,
    )

    if not ledger_enabled():
        return body, 0
    key = canonical_failure_key(name, args, body, failed)
    count = deps.ledger.get(key, 0) + 1
    deps.ledger[key] = count
    if count == 1:
        return body, 0
    code = extract_exit_code(body)
    return (
        f"REPEATED FAILURE (repeated {count}x): the same {name} call "
        f"(exit={code}) failed with an identical result as an earlier call. "
        "The full result was already shown at the first occurrence — do not "
        "repeat this exact call; change approach."
    ), count


def _is_adverse(name: str, body: str, failed: str | None) -> bool:
    """w3-4: a call counts as a failure for the ledger/stagnation when it
    was flagged by the tool (``failed``) or, for bash-shaped results,
    exited non-zero (the body carries ``[exit_code] N``)."""
    from shlepa_agent.state import extract_exit_code

    if failed is not None:
        return True
    code = extract_exit_code(body)
    return code not in ("?", "0")


def _stagnation_track(
    deps: "AgentDeps",
    name: str,
    args: Mapping[str, Any] | None,
    body: str,
    failed: str | None,
) -> None:
    """w3-4: shadow-only stagnation signal — >=3 consecutive identical
    failed calls within one phase log a ``stagnation`` event. No
    blocking, no synthetic result, never raises.
    """
    try:
        from shlepa_agent.log import _log_event
        from shlepa_agent.state import canonical_failure_key, stagnation_check

        phase_id = deps.phase_window.phase_id if deps.phase_window else "none"
        if failed is None:
            # a non-identical (successful) call breaks the streak
            deps.stagnation["phase_id"] = phase_id
            deps.stagnation["seq"] = []
            return
        key = canonical_failure_key(name, args, body, failed)
        streak = stagnation_check(deps.stagnation, phase_id, key)
        if streak is not None:
            _log_event(
                "stagnation",
                phase=phase_id,
                tool=name,
                streak=streak,
                key=key[:120],
                note="shadow only — no blocking",
            )
    except Exception:  # pragma: no cover - defensive
        pass


def finalizing_result(
    ctx: "RunContext[AgentDeps]",
    name: str,
    started: float,
    args: Mapping[str, Any] | None = None,
) -> str | None:
    """w3-2: if the current phase is inside its finalization reserve,
    return a synthetic FINALIZING result for an exploratory tool call
    (bash/search/recon) WITHOUT executing it; None otherwise.

    write/edit (and read) are intentionally untouched — finishing the
    deliverable must keep working.
    """
    from shlepa_agent.budget import finalize_reserve

    w = ctx.deps.phase_window
    if w is None:
        return None
    remaining = w.cap - (time.monotonic() - w.start)
    if remaining > finalize_reserve():
        return None
    return format_tool_result(
        ctx,
        name,
        "<not executed>",
        started,
        args=args,
        failed=(
            f"FINALIZING: {name} is disabled in the last "
            f"{finalize_reserve():g}s of the {w.phase_id} phase — "
            "write the deliverable now"
        ),
    )


def format_tool_result(
    ctx: "RunContext[AgentDeps]",
    name: str,
    body: str,
    started: float,
    *,
    args: Mapping[str, Any] | None = None,
    note: str | None = None,
    failed: str | None = None,
    untrusted: bool = False,
) -> str:
    """Render the instrumented result of a tool call.

    Layout (one result per tool call):

    - header line: ``[tool] name(arg1=..., arg2=...)``
    - timing line: ``spent`` (tool wall time), ``ended_at`` (seconds into
      the run)
    - optional ``NOTE:`` line (e.g. clamped parameters)
    - optional ``FAILED:`` line (only on tool failure)
    - the tool output: wrapped in ``UNTRUSTED TEXT`` markers when it carries
      environment data (read/bash), plain otherwise (write/edit status)

    ``started`` is the ``time.monotonic()`` value captured at tool entry.
    """
    from shlepa_agent.log import _log_event

    spent = time.monotonic() - started
    _log_event("tool_completed", tool=name, duration_sec=spent, failed=bool(failed))
    ended = ctx.deps.clock()
    argstr = ", ".join(f"{k}={_short(v)}" for k, v in (args or {}).items())
    lines = [
        f"[tool] {name}({argstr})",
        f"  spent={spent:.2f}s ended_at={ended:.1f}s",
    ]
    repeated = 0
    if note:
        lines.append(f"  NOTE: {note}")
    if failed:
        lines.append(f"  FAILED: {failed}")
    if _is_adverse(name, body, failed):
        # w3-4: the stagnation key is computed on the ORIGINAL body —
        # before the ledger compresses the body of repeated failures.
        _stagnation_track(ctx.deps, name, args, body, failed or "")
        body, repeated = _ledger_compress(ctx.deps, name, args, body, failed or "")
    else:
        _stagnation_track(ctx.deps, name, args, body, None)
    if untrusted:
        lines += [
            "UNTRUSTED TEXT ---------------",
            body or "<empty>",
            "END OF UNTRUSTED TEXT-----------",
        ]
    else:
        lines.append(body)
    if repeated:
        lines.append(f"  [ledger] repeated {repeated}x — result compressed")
    return "\n".join(lines)


@dataclass(frozen=True)
class Tool:
    """One agent tool: name, short usage note, async implementation.

    ``run`` has the pydantic-ai tool signature
    ``(ctx: RunContext[AgentDeps], **args) -> str``. Its docstring is the
    tool description sent to the model in the API tool spec; ``note`` is a
    one-line usage hint rendered into the request template's ``tools`` block.
    """

    name: str
    note: str
    run: Callable[..., Any]


def resolve_path(path: str, workdir: Path) -> Path:
    if Path(path).is_absolute():
        return Path(path).resolve()
    return (workdir / path).resolve()
