"""Compact run-state file for post-run analysis.

Written after every phase (and at run start) so that a run can be analyzed
after the fact without the LLM trace: the fixed regime, cycle count, and
each phase's structured outcome (status, summary, deliverable, error).

Location: $SHLEPA_STATE_FILE when set, else /tmp/shlepa_state.json — the
file is deliberately NOT written into the task workdir (the agent runs
inside contest containers; the workdir must stay clean for the grader).

The file is dev/trace convenience only — the agent never reads it back.
Failures to write it are swallowed (a broken state file must never affect
the run).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from shlepa_agent.budget import regime
from shlepa_agent.phases.base import RunState

STATE_FILENAME = "shlepa_state.json"
DEFAULT_STATE_PATH = Path("/tmp") / STATE_FILENAME


def _state_path() -> Path:
    """State-file location: $SHLEPA_STATE_FILE override, else /tmp default."""
    raw = os.environ.get("SHLEPA_STATE_FILE")
    if raw:
        return Path(raw)
    return DEFAULT_STATE_PATH


# -- LAST_TOOLS: deterministic tail of a phase conversation ------------------
#: Default number of recent tool calls carried into the next phase on a
#: hand-off (env-overridable via SHLEPA_LAST_TOOLS_N, A/B knob).
LAST_TOOLS_N = 6
LAST_TOOLS_ARGS_CAP = 200
LAST_TOOLS_RESULT_CAP = 400
#: The typed output tool is not a "tool call" for hand-off purposes.
_NON_TOOL_TOOLS = frozenset({"final_result"})


def last_tools_n() -> int:
    """LAST_TOOLS tail size: SHLEPA_LAST_TOOLS_N override, else the default."""
    raw = os.environ.get("SHLEPA_LAST_TOOLS_N")
    if raw:
        try:
            value = int(raw)
            if value >= 0:
                return value
        except ValueError:
            pass  # invalid: fall back to the default
    return LAST_TOOLS_N


def extract_last_tools(
    messages: list[Any],
    n: int | None = None,
) -> list[dict[str, str]]:
    """Deterministic LAST_TOOLS extraction from a phase conversation.

    Walks the pydantic-ai message list (``model.last_messages``) in order,
    pairs each ``ToolCallPart`` with the ``ToolReturnPart`` that follows
    (matched by tool_call_id, then by tool name), and returns the last
    ``n`` tool calls as ``{"tool", "args", "result"}`` dicts with capped
    text (args <= 200 chars, result <= 400 chars). The typed output tool
    (``final_result``) is excluded; a call without a visible result gets
    an empty result. Pure stdlib + pydantic-ai message types; never raises
    on unexpected shapes (returns what it can parse).
    """
    if n is None:
        n = last_tools_n()
    from pydantic_ai.messages import ToolCallPart, ToolReturnPart

    calls: list[dict[str, str]] = []
    open_by_id: dict[str, dict[str, str]] = {}
    for message in messages or []:
        parts = getattr(message, "parts", None) or []
        for part in parts:
            if isinstance(part, ToolCallPart):
                if part.tool_name in _NON_TOOL_TOOLS:
                    continue
                args = part.args
                args_text = args if isinstance(args, str) else _safe_repr(args)
                call = {
                    "tool": part.tool_name,
                    "args": _cap(args_text, LAST_TOOLS_ARGS_CAP),
                    "result": "",
                }
                calls.append(call)
                if part.tool_call_id:
                    open_by_id[part.tool_call_id] = call
            elif isinstance(part, ToolReturnPart):
                target = None
                if part.tool_call_id and part.tool_call_id in open_by_id:
                    target = open_by_id.pop(part.tool_call_id)
                else:
                    # fall back to the most recent unmatched call of the
                    # same tool
                    for call in reversed(calls):
                        if (
                            call["tool"] == part.tool_name
                            and not call["result"]
                        ):
                            target = call
                            break
                if target is not None:
                    target["result"] = _cap(
                        _content_text(part.content), LAST_TOOLS_RESULT_CAP
                    )
    return calls[-n:] if n else []


def _safe_repr(value: Any) -> str:
    try:
        import json as _json

        return _json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _content_text(content: Any) -> str:
    """Flatten a ToolReturnPart.content (str or a list of part objects)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        chunks: list[str] = []
        for item in content:
            text = getattr(item, "content", None)
            chunks.append(text if isinstance(text, str) else str(item))
        return "\n".join(chunks)
    return str(content)


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "[...]"


def render_last_tools(entries: list[dict[str, str]]) -> str:
    """Render extracted LAST_TOOLS entries as a prompt block (empty -> "")."""
    if not entries:
        return ""
    lines = [
        "LAST TOOLS (deterministic tail of the previous phase conversation)"
    ]
    for entry in entries:
        args = entry.get("args") or ""
        result = entry.get("result") or ""
        lines.append(f"- {entry['tool']}({args})")
        if result:
            lines.append(f"  -> {result}")
    return "\n".join(lines)


def save_state(state: RunState) -> None:
    """Atomically (re)write the run-state file (never into the workdir)."""
    try:
        data = {
            "elapsed": round(state.model.elapsed(), 1),
            "cycles": state.cycles,
            "regime": regime(),
            "results": {
                phase_id: {
                    "status": res.status,
                    "summary": (res.summary or "")[:4000],
                    "deliverable": res.deliverable,
                    "error": res.error,
                    # the final_ask text left by a cut phase (e.g. the
                    # salvaged plan the work phase executed)
                    "note": (res.note or "")[:4000] or None,
                }
                for phase_id, res in state.results.items()
            },
        }
        target = _state_path()
        tmp = Path(str(target) + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, default=str)
        os.replace(tmp, target)
    except OSError:
        pass  # never let state-file IO affect the run


# -- failure ledger canonicalizer (w3-3; reused by stagnation w3-4) --------

_WS_RE = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    """Collapse all whitespace runs to single spaces and trim."""
    return _WS_RE.sub(" ", str(text)).strip()


def canonical_failure_key(
    name: str,
    args: "Mapping[str, Any] | None",
    body: str,
    failed: str,
) -> str:
    """Stable fingerprint of one failed tool call (w3-3).

    Exact tool name + whitespace-normalized args + normalized outcome.
    The volatile instrumentation envelope (``[tool]`` header, spent /
    ended_at lines) is added by ``format_tool_result`` after this key is
    computed, so nothing else is stripped.
    """
    norm_args = ",".join(
        f"{k}={normalize_ws(v)}" for k, v in sorted((args or {}).items())
    )
    key = normalize_ws(f"{name}|{norm_args}|{failed}|{body}")
    return key[:4000]


def extract_exit_code(body: str) -> str:
    """Best-effort exit code from a bash-shaped body; "?" when absent."""
    m = re.search(r"\[exit_code\] (\d+)", body)
    if m:
        return m.group(1)
    m = re.search(r"exit (\d+)", body)
    if m:
        return m.group(1)
    return "?"


def ledger_enabled() -> bool:
    """SHLEPA_LEDGER knob (w3-3): on by default; 0/false/off disables."""
    v = os.environ.get("SHLEPA_LEDGER", "1").strip().lower()
    return v not in ("0", "false", "off")


def stagnation_check(state: dict, phase_id: str, key: str) -> int | None:
    """w3-4: >=3 consecutive identical failure keys WITHIN ONE phase.

    ``state`` is the mutable per-run dict held by ``AgentDeps.stagnation``
    (``{"phase_id": ..., "seq": [...]}``); a different phase or a
    different key breaks the streak (the tail of ``seq`` encodes the
    current run of identical keys). Returns the consecutive streak length
    when the shadow threshold is met (>=3), else None. Shadow-only: no
    blocking.
    """
    if state.get("phase_id") != phase_id:
        state["phase_id"] = phase_id
        state["seq"] = []
    seq: list[str] = state["seq"]
    seq.append(key)
    if len(seq) > 8:  # bounded memory; the threshold is 3
        del seq[: len(seq) - 8]
    if len(seq) < 3 or not (seq[-1] == seq[-2] == seq[-3]):
        return None
    n = 1
    for prev in reversed(seq[:-1]):
        if prev == key:
            n += 1
        else:
            break
    return n
