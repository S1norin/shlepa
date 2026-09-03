"""Tests for the trace digest builder (trace_digest).

The digest is built from the trace_to_dict JSON shape (t7), so the
synthetic traces here are plain dicts.
"""

import json
from pathlib import Path

from shlepa_cli import trace_digest

FIXTURES = Path(__file__).parent / "fixtures"


def _llm_span(i, prompt, completion, start_ns=None, phase=None):
    start = (start_ns if start_ns is not None else i) * 1_000_000_000
    attributes = {
        "llm.token_count.prompt": str(prompt),
        "llm.token_count.completion": str(completion),
    }
    if phase is not None:
        attributes["shlepa.phase_id"] = phase
    return {
        "span_id": f"llm-{i}",
        "parent_id": None,
        "name": f"LLM turn {i}",
        "span_type": "LLM",
        "model_name": "Qwen",
        "status": "OK",
        "start_time_ns": start,
        "end_time_ns": start + 1_000_000_000,
        "attributes": attributes,
        "events": [],
        "inputs": None,
        "outputs": None,
    }


def _tool_span(
    i,
    name="bash",
    args="ls -la",
    result="ok",
    status="OK",
    start_ns=None,
):
    start = (start_ns if start_ns is not None else i) * 1_000_000_000
    attributes = {
        "tool.name": name,
        "tool.call.arguments": args
        if isinstance(args, str)
        else json.dumps(args, sort_keys=True),
    }
    if result is not None:
        attributes["tool.call.result"] = (
            result if isinstance(result, str) else json.dumps(result)
        )
    return {
        "span_id": f"tool-{i}",
        "parent_id": "root",
        "name": name,
        "span_type": "TOOL",
        "model_name": None,
        "status": status,
        "start_time_ns": start,
        "end_time_ns": start + 500_000_000,
        "attributes": attributes,
        "events": [],
        "inputs": None,
        "outputs": None,
    }


def _trace(spans, task="contest-hello-file", state="OK"):
    return {
        "trace_id": "tr-1",
        "task": task,
        "state": state,
        "request_time": 1,
        "tags": {"service.name": "shlepa-agent"},
        "spans": spans,
    }


def test_loop_signal_positive_on_repeated_bash_cmd():
    spans = [_tool_span(i, "bash", "while true; do curl x; done", result="x")
             for i in range(5)]
    digest = trace_digest.build_digest(_trace(spans))
    assert "loop" in digest.lower()
    assert "bash" in digest
    assert "5" in digest  # the reported count


def test_loop_signal_negative_on_distinct_args():
    spans = [_tool_span(i, "bash", f"ls dir-{i}") for i in range(6)]
    digest = trace_digest.build_digest(_trace(spans))
    assert "loop" not in digest.lower() or "no failure signals" in digest.lower()


def test_header_aggregates_tokens_calls_and_duration():
    spans = [
        _llm_span(1, 100, 10),
        _llm_span(2, 200, 20),
        _llm_span(3, 300, 30),
        _tool_span(4, "read_file", "path=/x"),
        _tool_span(5, "read_file", "path=/y", status="ERROR"),
    ]
    digest = trace_digest.build_digest(_trace(spans))
    assert "contest-hello-file" in digest
    assert "3" in digest  # llm_calls
    assert "600" in digest  # total prompt tokens
    assert "60" in digest  # total completion tokens
    assert "peak context" in digest.lower()
    assert "300" in digest  # peak = max prompt
    assert "tool_errors" in digest.lower() or "tool errors" in digest.lower()
    assert "1" in digest  # one ERROR tool span


def test_header_per_phase_token_lines():
    spans = [
        _llm_span(1, 100, 10, phase="work"),
        _llm_span(2, 50, 5, phase="plan"),
        _llm_span(3, 20, 2, phase="commit"),
    ]
    digest = trace_digest.build_digest(_trace(spans))
    plan_line = next(l for l in digest.splitlines() if l.startswith("- tokens[plan]:"))
    work_line = next(l for l in digest.splitlines() if l.startswith("- tokens[work]:"))
    commit_line = next(l for l in digest.splitlines() if l.startswith("- tokens[commit]:"))
    assert "50 in / 5 out" in plan_line
    assert "100 in / 10 out" in work_line
    assert "20 in / 2 out" in commit_line
    # plan -> work -> commit ordering regardless of span order
    assert digest.index(plan_line) < digest.index(work_line) < digest.index(commit_line)


def test_per_phase_lines_absent_for_unlabeled_traces():
    spans = [_llm_span(1, 100, 10), _llm_span(2, 200, 20)]
    digest = trace_digest.build_digest(_trace(spans))
    assert "tokens[" not in digest


def test_per_phase_tokens_helper_ignores_unlabeled_spans():
    spans = [
        _llm_span(1, 100, 10, phase="plan"),
        _llm_span(2, 200, 20),  # unlabeled: excluded
    ]
    assert trace_digest.per_phase_tokens(_trace(spans)) == [("plan", 100, 10)]


def test_repeated_identical_tool_results_counted():
    spans = [
        _tool_span(1, "read_file", "path=/a", result="SAME"),
        _tool_span(2, "read_file", "path=/b", result="SAME"),
        _tool_span(3, "read_file", "path=/c", result="OTHER"),
    ]
    digest = trace_digest.build_digest(_trace(spans))
    assert "repeated" in digest.lower()
    assert "2" in digest


def test_clean_trace_reports_no_signals():
    spans = [
        _llm_span(1, 10, 10),
        _tool_span(2, "bash", "ls", result="a"),
        _tool_span(3, "bash", "pwd", result="b"),
    ]
    digest = trace_digest.build_digest(_trace(spans))
    assert "no failure signals" in digest.lower()


def test_empty_trace_digest_renders():
    digest = trace_digest.build_digest(_trace([]))
    assert "trace digest" in digest.lower()
    assert "tr-1" in digest


def test_real_fixture_token_parse():
    """Golden fixture: a REAL exported LLM span (trace tr-a5420d2d, 2026-08-28)
    carrying both semconv key sets. Fails loudly if the agent's
    instrumentation stops emitting these usage attributes."""
    span = json.loads((FIXTURES / "llm_span_real.json").read_text())
    assert trace_digest.span_prompt_tokens(span) == 581
    assert trace_digest.span_completion_tokens(span) == 165


def test_tokens_missing_signal():
    llm = _llm_span(1, 0, 0)
    llm["attributes"] = {"gen_ai.operation.name": "chat"}  # no usage
    trace = {
        "trace_id": "tr-x",
        "task": "t",
        "state": "OK",
        "spans": [llm],
    }
    assert "tokens_missing" in trace_digest.trace_signals(trace)

    good = _llm_span(1, 10, 2)
    trace2 = {
        "trace_id": "tr-x",
        "task": "t",
        "state": "OK",
        "spans": [good],
    }
    assert "tokens_missing" not in trace_digest.trace_signals(trace2)


def test_token_keys_accept_gen_ai_semconv():
    span = _llm_span(1, 0, 0)
    span["attributes"] = {
        "gen_ai.usage.input_tokens": "42",
        "gen_ai.usage.output_tokens": "7",
    }
    digest = trace_digest.build_digest(_trace([span]))
    assert "42 in / 7 out" in digest
    assert "peak context: 42" in digest


def test_repeated_empty_results_not_flagged():
    # no-op commands return '' — that is not a stuck loop
    spans = [_tool_span(i, "bash", f"true {i}", result="") for i in range(10)]
    trace = _trace(spans)
    assert "repeated_results" not in trace_digest.trace_signals(trace)


def test_repeated_nonempty_results_still_flagged():
    spans = [
        _tool_span(1, "bash", "a", result="same output"),
        _tool_span(2, "bash", "b", result="same output"),
        _tool_span(3, "bash", "c", result="same output"),
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    # one repeated result value, seen 3 times
    assert "repeated_results:1" in signals


def test_loop_signal_contains_args_excerpt():
    spans = [_tool_span(i, "bash", "ls -la /tmp", result="x") for i in range(4)]
    signals = trace_digest.trace_signals(_trace(spans))
    loop = [s for s in signals if s.startswith("loop:bash:4")]
    assert loop, signals
    assert "ls -la /tmp" in loop[0]


def test_digest_loop_line_contains_args_excerpt():
    spans = [_tool_span(i, "bash", "ls -la /tmp", result="x") for i in range(4)]
    digest = trace_digest.build_digest(_trace(spans))
    lines = [
        ln
        for ln in digest.splitlines()
        if "loop" in ln.lower() and "bash" in ln
    ]
    assert lines, digest
    assert "ls -la /tmp" in lines[0]


# --- thinking-part signals (issue #41) -------------------------------------


def _llm_span_with_messages(i, parts):
    span = _llm_span(i, 10, 2)
    span["attributes"]["gen_ai.output.messages"] = json.dumps(
        [{"role": "assistant", "parts": parts}]
    )
    return span


def test_thinking_parts_counted_in_digest_header():
    spans = [
        _llm_span_with_messages(
            1,
            [
                {"type": "thinking", "content": "plan the approach"},
                {"type": "text", "content": "answer"},
            ],
        ),
        _llm_span_with_messages(
            2,
            [
                {"type": "thinking", "content": "step two"},
                {"type": "tool_call", "id": "c", "name": "bash",
                 "arguments": "{}"},
            ],
        ),
    ]
    digest = trace_digest.build_digest(_trace(spans))
    assert "thinking_parts: 2" in digest
    assert "n/a" not in digest


def test_no_thinking_signal_when_messages_present_but_zero_thinking():
    spans = [
        _llm_span_with_messages(1, [{"type": "text", "content": "answer"}]),
        _llm_span_with_messages(
            2, [{"type": "tool_call", "id": "c", "name": "bash",
                 "arguments": "{}"}]
        ),
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    assert "no_thinking" in signals
    assert "messages_missing" not in signals


def test_messages_missing_signal_when_no_output_messages():
    spans = [_llm_span(1, 10, 2)]  # carries usage but no messages
    signals = trace_digest.trace_signals(_trace(spans))
    assert "messages_missing" in signals
    assert "no_thinking" not in signals
    digest = trace_digest.build_digest(_trace(spans))
    assert "thinking_parts: n/a" in digest


def test_malformed_output_messages_treated_as_missing_not_no_thinking():
    span = _llm_span(1, 10, 2)
    span["attributes"]["gen_ai.output.messages"] = "{not json"
    signals = trace_digest.trace_signals(_trace([span]))
    assert "messages_missing" in signals
    assert "no_thinking" not in signals


def test_thinking_signals_absent_without_llm_spans():
    signals = trace_digest.trace_signals(_trace([_tool_span(1)]))
    assert "no_thinking" not in signals
    assert "messages_missing" not in signals


def test_real_fixture_thinking_parts():
    """Golden fixture: the real span (tr-a5420d2d) has a thinking part."""
    span = json.loads((FIXTURES / "llm_span_real.json").read_text())
    assert trace_digest.thinking_parts_count(span) >= 1


# --- F3: real gen_ai.* / legacy key families (issue #68) -------------------
# Current traces carry gen_ai.tool.* + tool.parameters/output.value, never
# the bare tool.call.arguments / tool.call.result the pre-F3 digest looked
# for (which collapsed every signature to empty args -> mass false loops).


def _tool_span_real_keys(i, name="bash", args=None, result="ok"):
    """Tool span shaped like the real traces (gen_ai + legacy families)."""
    span = _tool_span(i, name=name, args=None, result=None)
    attrs = {
        "gen_ai.tool.name": name,
        "gen_ai.tool.call.id": f"call-{i}",
    }
    if args is not None:
        attrs["gen_ai.tool.call.arguments"] = (
            args if isinstance(args, dict) else json.loads(args)
        )
        attrs["tool.parameters"] = attrs["gen_ai.tool.call.arguments"]
    if result is not None:
        attrs["gen_ai.tool.call.result"] = result
        attrs["output.value"] = result
    attrs["tool.name"] = name
    span["attributes"] = attrs
    return span


def test_loop_positive_on_repeated_args_genai_keys():
    spans = [
        _tool_span_real_keys(i, "bash", {"command": "curl http://x"})
        for i in range(5)
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    loop = [s for s in signals if s.startswith("loop:bash:5")]
    assert loop, signals
    assert "curl http://x" in loop[0]


def test_loop_negative_on_distinct_args_genai_keys():
    spans = [
        _tool_span_real_keys(i, "bash", {"command": f"ls dir-{i}"})
        for i in range(8)
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    assert not [s for s in signals if s.startswith("loop:")], signals


def test_repeated_results_uses_genai_result_key():
    spans = [
        _tool_span_real_keys(1, "bash", {"command": "a"}, "same output"),
        _tool_span_real_keys(2, "bash", {"command": "b"}, "same output"),
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    assert "repeated_results:1" in signals


def test_repeated_results_empty_never_counts():
    spans = [
        _tool_span_real_keys(i, "bash", {"command": f"c-{i}"}, "")
        for i in range(4)
    ]
    signals = trace_digest.trace_signals(_trace(spans))
    assert not [s for s in signals if s.startswith("repeated_results:")], signals


def test_legacy_tool_parameters_args_still_supported():
    # Pre-gen_ai traces: only the legacy tool.name + tool.parameters pair.
    spans = []
    for i in range(5):
        span = _tool_span(i, name="bash", args=None, result=None)
        span["attributes"] = {
            "tool.name": "bash",
            "tool.parameters": {"command": "ping host"},
        }
        spans.append(span)
    signals = trace_digest.trace_signals(_trace(spans))
    loop = [s for s in signals if s.startswith("loop:bash:5")]
    assert loop, signals
    assert "ping host" in loop[0]
