"""Compact Markdown digest of one agent trace for LLM analysis.

Built from the trace_to_dict JSON shape (see trace_export): a header
with run-level numbers (incl. thinking_parts, counted from typed
output messages), a per-span timeline, and a deterministic
failure-signals section (loop detection, tool errors, peak context,
repeated tool results). Pure function: dict in, Markdown out.

Signals are intentionally simple and explainable — the analysis LLM
reads the digest first and pulls the full traces/<task>.json only for
the flagged tasks.
"""

from __future__ import annotations

import hashlib
import json

__all__ = [
    "build_digest",
    "detect_loops",
    "thinking_parts_count",
    "tool_signature",
    "trace_signals",
]

#: A signature repeated this many times inside the rolling window is a loop.
LOOP_THRESHOLD = 4
#: Rolling window size (in tool calls) for the loop detector.
LOOP_WINDOW = 6

# OpenInference emits either the legacy llm.* keys or the gen_ai.*
# (OpenTelemetry semantic convention) keys depending on version; accept both.
_PROMPT_KEYS = ("llm.token_count.prompt", "gen_ai.usage.input_tokens")
_COMPLETION_KEYS = (
    "llm.token_count.completion",
    "gen_ai.usage.output_tokens",
)
#: OpenInference serializes LLM output messages (with typed parts, incl.
#: type:thinking) under this key; pre-v1 traces carry it not at all.
_OUTPUT_MESSAGES_KEY = "gen_ai.output.messages"
_TOOL_NAME_KEY = "tool.name"
_TOOL_ARGS_KEY = "tool.call.arguments"
_TOOL_RESULT_KEY = "tool.call.result"


def _norm(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _tokens(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _attr_first(attrs: dict, keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in attrs:
            return _tokens(attrs.get(key))
    return 0


def span_prompt_tokens(span: dict) -> int:
    return _attr_first(span.get("attributes") or {}, _PROMPT_KEYS)


def span_completion_tokens(span: dict) -> int:
    return _attr_first(span.get("attributes") or {}, _COMPLETION_KEYS)


def _output_messages(span: dict):
    """Parsed gen_ai.output.messages, or None when absent/malformed.

    Accepts the OTLP-side JSON string and the server-side already-parsed
    list; anything else is treated as missing (never raises).
    """
    value = (span.get("attributes") or {}).get(_OUTPUT_MESSAGES_KEY)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, (list, tuple)) else None


def _span_has_output_messages(span: dict) -> bool:
    return _output_messages(span) is not None


def thinking_parts_count(span: dict) -> int:
    """Number of non-empty type:thinking parts in the span's output.

    Legacy flat llm.output_messages.* keys carry no part types, so they
    cannot be counted; such spans report 0 (their absence from the
    typed key is flagged by the messages_missing signal instead).
    """
    messages = _output_messages(span)
    if messages is None:
        return 0
    count = 0
    for message in messages:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "thinking" and str(
                part.get("content") or ""
            ).strip():
                count += 1
    return count


def _is_error(status) -> bool:
    if status is None:
        return False
    if isinstance(status, dict):
        code = status.get("status_code", status.get("code", ""))
        return "error" in str(code).lower()
    return "error" in str(status).lower()


def _sorted_spans(trace: dict) -> list:
    spans = list(trace.get("spans") or [])
    spans.sort(key=lambda s: s.get("start_time_ns") or 0)
    return spans


def _llm_spans(trace: dict) -> list:
    return [s for s in _sorted_spans(trace) if s.get("span_type") == "LLM"]


def _tool_spans(trace: dict) -> list:
    return [s for s in _sorted_spans(trace) if s.get("span_type") == "TOOL"]


def tool_signature(span: dict) -> str:
    """Tool name + sha256 of the normalized arguments."""
    attrs = span.get("attributes") or {}
    name = attrs.get(_TOOL_NAME_KEY) or span.get("name") or "tool"
    return f"{name}:{hashlib.sha256(_norm(attrs.get(_TOOL_ARGS_KEY)).encode()).hexdigest()[:12]}"


def detect_loops(tool_spans: list) -> list[dict]:
    """Signatures hitting LOOP_THRESHOLD within a LOOP_WINDOW window.

    Returns [{'signature', 'count', 'tool', 'args'}] for each looping
    signature (count = total occurrences in the trace).
    """
    signatures = [tool_signature(span) for span in tool_spans]
    total: dict[str, int] = {}
    for sig in signatures:
        total[sig] = total.get(sig, 0) + 1
    windows: list[list[str]]
    if len(signatures) >= LOOP_WINDOW:
        windows = [
            signatures[start:start + LOOP_WINDOW]
            for start in range(len(signatures) - LOOP_WINDOW + 1)
        ]
    else:
        # Fewer calls than one window: the whole trace is one window.
        windows = [signatures]
    loops: list[str] = []
    for window in windows:
        for sig in {s for s in window if window.count(s) >= LOOP_THRESHOLD}:
            if sig not in loops:
                loops.append(sig)
    result = []
    for sig in loops:
        span = next(
            (
                s
                for s in tool_spans
                if tool_signature(s) == sig
            ),
            {},
        )
        attrs = span.get("attributes") or {}
        result.append(
            {
                "signature": sig,
                "count": total[sig],
                "tool": attrs.get(_TOOL_NAME_KEY) or "tool",
                "args": _norm(attrs.get(_TOOL_ARGS_KEY))[:120],
            }
        )
    return result


def trace_signals(trace: dict) -> list[str]:
    """Short machine-readable signal tags for one trace dict.

    Used in manifest.jsonl: 'loop:<tool>:<count>', 'tool_errors:<n>',
    'repeated_results:<n>', 'tokens_missing', 'no_thinking',
    'messages_missing'.
    """
    tools = _tool_spans(trace)
    signals: list[str] = []
    for loop in detect_loops(tools):
        # args excerpt so the analysis LLM can judge polling vs. stuck
        # loop without pulling the full trace
        excerpt = (loop["args"] or "").replace("\n", " ")[:60]
        signals.append(f"loop:{loop['tool']}:{loop['count']}:{excerpt}")
    errors = [s for s in tools if _is_error(s.get("status"))]
    if errors:
        signals.append(f"tool_errors:{len(errors)}")
    repeated = _repeated_results(tools)
    if repeated:
        signals.append(f"repeated_results:{repeated}")
    # Unfinished LLM spans (timeout/crash mid-call) carry no usage
    # attributes; flag it so an analysis LLM does not mistake "no data"
    # for "zero tokens".
    llm_spans = _llm_spans(trace)
    usage_keys = _PROMPT_KEYS + _COMPLETION_KEYS
    has_usage = any(
        any(key in (s.get("attributes") or {}) for key in usage_keys)
        for s in llm_spans
    )
    if llm_spans and not has_usage:
        signals.append("tokens_missing")
    # Reasoning capture: typed output messages present -> count thinking
    # parts (0 => the model really did not reason); absent => the trace
    # predates message capture and "no thinking" is unknowable, so the
    # two signals are mutually exclusive.
    if llm_spans:
        has_messages = any(_span_has_output_messages(s) for s in llm_spans)
        if has_messages:
            if sum(thinking_parts_count(s) for s in llm_spans) == 0:
                signals.append("no_thinking")
        else:
            signals.append("messages_missing")
    return signals


def _repeated_results(tool_spans: list) -> int:
    """Number of non-empty tool-result values that occur more than once.

    Empty/whitespace-only results are skipped: no-op commands returning
    '' is not a stuck loop (main false-positive source).
    """
    counts: dict[str, int] = {}
    for span in tool_spans:
        attrs = span.get("attributes") or {}
        value = attrs.get(_TOOL_RESULT_KEY)
        if value is None or not str(value).strip():
            continue
        key = hashlib.sha256(_norm(value).encode()).hexdigest()
        counts[key] = counts.get(key, 0) + 1
    return sum(1 for count in counts.values() if count > 1)


def _duration_sec(trace: dict) -> float:
    starts = [s.get("start_time_ns") or 0 for s in trace.get("spans") or []]
    ends = [s.get("end_time_ns") or 0 for s in trace.get("spans") or []]
    if not starts or not ends:
        return 0.0
    return max(0.0, (max(ends) - min(starts)) / 1_000_000_000)


def build_digest(trace: dict) -> str:
    """Render the Markdown digest for one trace_to_dict dict."""
    llm = _llm_spans(trace)
    tools = _tool_spans(trace)
    prompt_tokens = sum(span_prompt_tokens(s) for s in llm)
    completion_tokens = sum(span_completion_tokens(s) for s in llm)
    peak_context = max((span_prompt_tokens(s) for s in llm), default=0)
    tool_errors = [s for s in tools if _is_error(s.get("status"))]
    loops = detect_loops(tools)
    repeated = _repeated_results(tools)

    lines: list[str] = []
    lines.append(f"# Trace digest: {trace.get('task') or '(unknown task)'}")
    lines.append("")
    lines.append(f"- trace_id: {trace.get('trace_id')}")
    lines.append(f"- state: {trace.get('state')}")
    lines.append(f"- duration: {_duration_sec(trace):.1f}s")
    lines.append(
        f"- tokens: {prompt_tokens} in / {completion_tokens} out "
        f"(total {prompt_tokens + completion_tokens})"
    )
    lines.append(f"- llm_calls: {len(llm)}")
    if llm:
        if any(_span_has_output_messages(s) for s in llm):
            thinking = sum(thinking_parts_count(s) for s in llm)
            lines.append(f"- thinking_parts: {thinking}")
        else:
            lines.append("- thinking_parts: n/a (no output messages)")
    lines.append(f"- tool_calls: {len(tools)}")
    lines.append(f"- tool_errors: {len(tool_errors)}")
    lines.append(f"- peak context: {peak_context} tokens (max LLM prompt)")
    lines.append("")
    lines.append("## Timeline")
    lines.append("")
    spans = _sorted_spans(trace)
    if not spans:
        lines.append("(no spans)")
    for i, span in enumerate(spans, 1):
        kind = span.get("span_type") or "?"
        name = span.get("name") or "?"
        status = span.get("status")
        if isinstance(status, dict):
            status = status.get("status_code", status)
        extra = ""
        if kind == "LLM":
            extra = (
                f" in={span_prompt_tokens(span)} "
                f"out={span_completion_tokens(span)}"
            )
        elif kind == "TOOL":
            extra = f" status={status}"
        lines.append(f"{i}. [{kind}] {name}{extra}")
    lines.append("")
    lines.append("## Failure signals")
    lines.append("")
    if not loops and not tool_errors and repeated == 0:
        lines.append("No failure signals.")
    else:
        for loop in loops:
            lines.append(
                f"- **loop**: `{loop['tool']}` with args `{loop['args']}` "
                f"called {loop['count']} times "
                f"(>= {LOOP_THRESHOLD} within a {LOOP_WINDOW}-call window)"
            )
        if tool_errors:
            names = ", ".join(
                ((s.get("attributes") or {}).get(_TOOL_NAME_KEY) or s.get("name"))
                for s in tool_errors
            )
            lines.append(f"- **tool errors**: {len(tool_errors)} ({names})")
        if repeated:
            lines.append(
                f"- **repeated tool results**: {repeated} result value(s) "
                f"returned by multiple different calls"
            )
    lines.append("")
    return "\n".join(lines)
