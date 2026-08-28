"""Tests for the trace digest builder (trace_digest).

The digest is built from the trace_to_dict JSON shape (t7), so the
synthetic traces here are plain dicts.
"""

import json
from pathlib import Path

from shlepa_cli import trace_digest

FIXTURES = Path(__file__).parent / "fixtures"


def _llm_span(i, prompt, completion, start_ns=None):
    start = (start_ns if start_ns is not None else i) * 1_000_000_000
    return {
        "span_id": f"llm-{i}",
        "parent_id": None,
        "name": f"LLM turn {i}",
        "span_type": "LLM",
        "model_name": "Qwen",
        "status": "OK",
        "start_time_ns": start,
        "end_time_ns": start + 1_000_000_000,
        "attributes": {
            "llm.token_count.prompt": str(prompt),
            "llm.token_count.completion": str(completion),
        },
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
