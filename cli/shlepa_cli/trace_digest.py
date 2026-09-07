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
    "per_phase_tokens",
    "span_cache_read_tokens",
    "span_phase_id",
    "thinking_parts_count",
    "tool_signature",
    "trace_cache_read_tokens",
    "trace_phase_tokens",
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
#: Cache-read tokens (a subset of the prompt tokens; OpenAI-compatible
#: endpoints report them via prompt_tokens_details.cached_tokens).
_CACHE_READ_KEYS = ("gen_ai.usage.cache_read.input_tokens",)
#: OpenInference serializes LLM output messages (with typed parts, incl.
#: type:thinking) under this key; pre-v1 traces carry it not at all.
_OUTPUT_MESSAGES_KEY = "gen_ai.output.messages"
# The agent's instrumentation emits two key families on TOOL spans: the
# OpenTelemetry semantic convention gen_ai.* keys and the legacy
# OpenInference tool.* keys (both always present in current traces).
# Accept both, preferring gen_ai.*, so identical calls hash identically.
# The pre-F3 digest only looked for tool.call.arguments / tool.call.result,
# keys no trace actually carries: every args normalized to "" and the loop
# detector flagged ~93% of real traces (issue #68).
_TOOL_NAME_KEYS = ("gen_ai.tool.name", "tool.name")
_TOOL_ARGS_KEYS = (
    "gen_ai.tool.call.arguments",
    "tool.parameters",
    "tool.call.arguments",
)
_TOOL_RESULT_KEYS = (
    "gen_ai.tool.call.result",
    "output.value",
    "tool.call.result",
)
# pydantic-ai names agent-run spans 'invoke_agent <agent name>' and puts
# the run's CUMULATIVE usage on that span under gen_ai.aggregated_usage.*
# (per-request chat spans carry gen_ai.usage.* and are not aggregated
# here to avoid double counting). Pre-phase-naming runs used the default
# agent name 'agent' and cannot be attributed to a phase.
_AGENT_RUN_NAME_PREFIX = "invoke_agent "
_LEGACY_AGENT_RUN_NAME = "agent"
_AGENT_USAGE_INPUT_KEY = "gen_ai.aggregated_usage.input_tokens"
_AGENT_USAGE_OUTPUT_KEY = "gen_ai.aggregated_usage.output_tokens"
_AGENT_USAGE_CACHE_READ_KEY = "gen_ai.aggregated_usage.cache_read.input_tokens"


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


def _attr_first_raw(attrs: dict, keys: tuple[str, ...]):
    """First present value among the key family (None when absent)."""
    for key in keys:
        if key in attrs:
            return attrs[key]
    return None


def span_prompt_tokens(span: dict) -> int:
    return _attr_first(span.get("attributes") or {}, _PROMPT_KEYS)


def span_completion_tokens(span: dict) -> int:
    return _attr_first(span.get("attributes") or {}, _COMPLETION_KEYS)


def span_phase_id(span: dict) -> str | None:
    """The pipeline phase (plan/work/commit) an LLM span ran in, if labeled.

    Traces exported before the F4 phase labels exist carry no such
    attribute; the digest then omits the per-phase breakdown entirely.
    """
    return (span.get("attributes") or {}).get("shlepa.phase_id")


#: Display order for per-phase token lines; unknown phases sort after.
_PHASE_ORDER = ("plan", "work", "commit")


def per_phase_tokens(trace: dict) -> list[tuple[str, int, int]]:
    """(phase, prompt_tokens, completion_tokens) per labeled phase.

    Ordered plan -> work -> commit, then any other phase alphabetically.
    Empty when no LLM span carries a phase label (pre-F4 traces).
    """
    totals: dict[str, list[int]] = {}
    for span in _llm_spans(trace):
        phase = span_phase_id(span)
        if phase is None:
            continue
        bucket = totals.setdefault(phase, [0, 0])
        bucket[0] += span_prompt_tokens(span)
        bucket[1] += span_completion_tokens(span)
    if not totals:
        return []
    ordered = sorted(
        totals.items(),
        key=lambda item: (
            _PHASE_ORDER.index(item[0]) if item[0] in _PHASE_ORDER else len(_PHASE_ORDER),
            item[0],
        ),
    )
    return [(phase, pin, pout) for phase, (pin, pout) in ordered]


def span_cache_read_tokens(span: dict) -> int:
    return _attr_first(span.get("attributes") or {}, _CACHE_READ_KEYS)


def trace_cache_read_tokens(trace: dict) -> int:
    return sum(span_cache_read_tokens(s) for s in _llm_spans(trace))


def trace_phase_tokens(trace: dict) -> dict:
    """Per-phase token totals from the phase agent-run spans.

    Returns {phase: {"in", "out", "cache_read"}} aggregated over the
    'invoke_agent <phase>' spans in start-time order (retries of a phase
    are summed). Runs that predate phase naming (agent name 'agent')
    yield an empty dict: the digest then shows totals only, no phase
    table. Issue #73.
    """
    by_phase: dict[str, dict[str, int]] = {}
    for span in _sorted_spans(trace):
        name = span.get("name") or ""
        if not name.startswith(_AGENT_RUN_NAME_PREFIX):
            continue
        phase = name[len(_AGENT_RUN_NAME_PREFIX):].strip()
        if not phase or phase == _LEGACY_AGENT_RUN_NAME:
            continue
        attrs = span.get("attributes") or {}
        bucket = by_phase.setdefault(
            phase, {"in": 0, "out": 0, "cache_read": 0}
        )
        bucket["in"] += _tokens(attrs.get(_AGENT_USAGE_INPUT_KEY))
        bucket["out"] += _tokens(attrs.get(_AGENT_USAGE_OUTPUT_KEY))
        bucket["cache_read"] += _tokens(attrs.get(_AGENT_USAGE_CACHE_READ_KEY))
    return by_phase


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
    name = _attr_first_raw(attrs, _TOOL_NAME_KEYS) or span.get("name") or "tool"
    args = _attr_first_raw(attrs, _TOOL_ARGS_KEYS)
    return (
        f"{name}:{hashlib.sha256(_norm(args).encode()).hexdigest()[:12]}"
    )


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
                "tool": _attr_first_raw(attrs, _TOOL_NAME_KEYS) or "tool",
                "args": _norm(_attr_first_raw(attrs, _TOOL_ARGS_KEYS))[:120],
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
        value = _attr_first_raw(attrs, _TOOL_RESULT_KEYS)
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
    # Cache reads are a subset of the prompt tokens; the line shows how
    # much of the input was actually new (paid) versus served from cache.
    # Omitted for legacy traces / endpoints without cache reporting.
    cache_read = trace_cache_read_tokens(trace)
    if cache_read:
        new_input = max(0, prompt_tokens - cache_read)
        ratio = cache_read / prompt_tokens if prompt_tokens else 0.0
        lines.append(
            f"- cache: {cache_read} read / {new_input} new input "
            f"({ratio:.0%} of input was cached)"
        )
    # Per-phase token totals from the phase agent-run spans ('invoke_agent
    # <phase-id>' with cumulative gen_ai.aggregated_usage.*); includes cache
    # reads, so the triple matches the MLflow per-phase metrics. Absent for
    # legacy traces (agent run named 'agent', no phase naming).
    phase_tokens = trace_phase_tokens(trace)
    if phase_tokens:
        lines.append("- phase tokens:")
        for phase, tokens in phase_tokens.items():
            lines.append(
                f"  - {phase}: {tokens['in']} in / {tokens['out']} out / "
                f"{tokens['cache_read']} cache read"
            )
    else:
        # Fallback for traces whose LLM spans carry the F4 phase label
        # (shlepa.phase_id) but whose agent-run spans predate phase naming.
        for phase, phase_in, phase_out in per_phase_tokens(trace):
            lines.append(
                f"- tokens[{phase}]: {phase_in} in / {phase_out} out "
                f"(total {phase_in + phase_out})"
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
                _attr_first_raw(s.get("attributes") or {}, _TOOL_NAME_KEYS)
                or s.get("name")
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
