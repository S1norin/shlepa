"""_ShlepaSpanProcessor: batch/task attrs on every span, cumulative tokens on root."""

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import telemetry  # noqa: E402


def _root_spans(exporter):
    return [s for s in exporter.get_finished_spans() if s.name == "agent.run"]


def test_child_llm_span_updates_root_cumulative_tokens():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("llm call 1") as child:
                child.set_attribute("llm.token_count.prompt", 100)
                child.set_attribute("llm.token_count.completion", 10)
            with tracer.start_as_current_span("llm call 2") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 50)
                child.set_attribute("gen_ai.usage.output_tokens", 5)
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.llm.cumulative_prompt_tokens") == 150
    assert attrs.get("shlepa.llm.cumulative_completion_tokens") == 15


def test_child_llm_span_updates_root_cache_totals():
    """cache_read / cache_creation attrs on LLM spans accumulate onto the
    root span as shlepa.llm.cumulative_cache_*_tokens."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("llm call 1") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 1000)
                child.set_attribute("gen_ai.usage.output_tokens", 10)
                child.set_attribute(
                    "gen_ai.usage.cache_read.input_tokens", 100
                )
                child.set_attribute(
                    "gen_ai.usage.cache_creation.input_tokens", 50
                )
            with tracer.start_as_current_span("llm call 2") as child:
                child.set_attribute("llm.token_count.prompt", 50)
                child.set_attribute("llm.token_count.completion", 5)
                child.set_attribute(
                    "gen_ai.usage.cache_read.input_tokens", 150
                )
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.llm.cumulative_prompt_tokens") == 1050
    assert attrs.get("shlepa.llm.cumulative_cache_read_tokens") == 250
    assert attrs.get("shlepa.llm.cumulative_cache_write_tokens") == 50


def test_no_cache_attrs_no_cache_stamps():
    """LLM spans without cache attributes: no cache attrs stamped on root."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("llm call") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 100)
                child.set_attribute("gen_ai.usage.output_tokens", 10)
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.llm.cumulative_prompt_tokens") == 100
    assert "shlepa.llm.cumulative_cache_read_tokens" not in attrs
    assert "shlepa.llm.cumulative_cache_write_tokens" not in attrs


def test_batch_attr_copied_to_child_spans(monkeypatch):
    monkeypatch.setenv("SLEPA_BATCH_ID", "20260828-000000-abc123")
    monkeypatch.setenv("SLEPA_TASK_SLUG", "task-x")
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("plain child"):
                pass
    finally:
        provider.shutdown()

    spans = exporter.get_finished_spans()
    roots = _root_spans(exporter)
    children = [s for s in spans if s.name != "agent.run"]
    assert roots, "no agent.run root span"
    assert children, "no child span"
    for span in roots + children:
        attrs = span.attributes
        assert attrs.get("shlepa.batch_id") == "20260828-000000-abc123"
        assert attrs.get("task") == "task-x"


def test_no_env_no_attrs_no_crash(monkeypatch):
    monkeypatch.delenv("SLEPA_BATCH_ID", raising=False)
    monkeypatch.delenv("SLEPA_TASK_SLUG", raising=False)
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("plain child"):
                pass
    finally:
        provider.shutdown()

    children = [s for s in exporter.get_finished_spans() if s.name != "agent.run"]
    assert children, "no child span"
    assert "shlepa.batch_id" not in children[0].attributes


def test_cache_tokens_accumulated_on_root():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("llm call 1") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 100)
                child.set_attribute(
                    "gen_ai.usage.cache_read.input_tokens", 80
                )
            with tracer.start_as_current_span("llm call 2") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 50)
                child.set_attribute(
                    "gen_ai.usage.details.cache_read_tokens", 50
                )
                child.set_attribute(
                    "gen_ai.usage.cache_write.input_tokens", 5
                )
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.llm.cumulative_cache_read_tokens") == 130
    assert attrs.get("shlepa.llm.cumulative_cache_write_tokens") == 5


def test_no_cache_attrs_when_endpoint_reports_none():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("llm call 1") as child:
                child.set_attribute("gen_ai.usage.input_tokens", 100)
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    attrs = roots[0].attributes
    assert "shlepa.llm.cumulative_cache_read_tokens" not in attrs
    assert "shlepa.llm.cumulative_cache_write_tokens" not in attrs


def test_non_llm_span_does_not_stamp_root():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("plain child"):
                pass
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert "shlepa.llm.cumulative_prompt_tokens" not in attrs
    assert "shlepa.llm.cumulative_completion_tokens" not in attrs


# --- Reasoning enrichment (thinking into span output) ----------------------


def _llm_span_with_thinking(provider, thinking="let me reason...", answer="final answer"):
    tracer = provider.get_tracer("t")
    with tracer.start_as_current_span("chat model") as child:
        child.set_attribute("gen_ai.operation.name", "chat")
        child.set_attribute(
            "gen_ai.output.messages",
            __import__("json").dumps(
                [
                    {
                        "role": "assistant",
                        "parts": [
                            {"type": "thinking", "content": thinking},
                            {"type": "text", "content": answer},
                        ],
                    }
                ]
            ),
        )
        child.set_attribute("output.value", answer)
    return "chat model"


def test_llm_span_output_enriched_with_thinking():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            name = _llm_span_with_thinking(provider)
    finally:
        provider.shutdown()

    span = next(s for s in exporter.get_finished_spans() if s.name == name)
    out = span.attributes.get("output.value")
    assert "let me reason..." in out  # reasoning visible in the output
    assert "final answer" in out  # ... followed by the final answer
    assert span.attributes.get("mlflow.spanOutputs") == out


def test_llm_span_without_thinking_untouched():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("chat model") as child:
                child.set_attribute("gen_ai.operation.name", "chat")
                child.set_attribute(
                    "gen_ai.output.messages",
                    __import__("json").dumps(
                        [{"role": "assistant",
                          "parts": [{"type": "text", "content": "just text"}]}]
                    ),
                )
                child.set_attribute("output.value", "just text")
    finally:
        provider.shutdown()

    span = next(s for s in exporter.get_finished_spans() if s.name == "chat model")
    assert span.attributes.get("output.value") == "just text"
    assert "mlflow.spanOutputs" not in span.attributes


def test_thinking_enrichment_never_raises_on_malformed_messages():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("chat model") as child:
                child.set_attribute("gen_ai.output.messages", "{not json")
                child.set_attribute("output.value", "answer")
    finally:
        provider.shutdown()

    span = next(s for s in exporter.get_finished_spans() if s.name == "chat model")
    assert span.attributes.get("output.value") == "answer"


def test_thinking_tool_call_span_output_has_thinking_and_tool_summary():
    """Non-final turns (thinking + tool call) have no output.value; the
    enriched output still shows the reasoning plus which tool was called."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            tracer = provider.get_tracer("t")
            with tracer.start_as_current_span("chat model") as child:
                child.set_attribute(
                    "gen_ai.output.messages",
                    __import__("json").dumps(
                        [
                            {
                                "role": "assistant",
                                "parts": [
                                    {"type": "thinking", "content": "check first"},
                                    {"type": "tool_call",
                                     "id": "c1", "name": "bash",
                                     "arguments": "{\"cmd\": \"ls\"}"},
                                ],
                            }
                        ]
                    ),
                )
                # No output.value: the instrumentation omits it for
                # non-final tool-call turns.
    finally:
        provider.shutdown()

    span = next(s for s in exporter.get_finished_spans() if s.name == "chat model")
    out = span.attributes.get("output.value")
    assert "check first" in out
    assert "bash" in out
