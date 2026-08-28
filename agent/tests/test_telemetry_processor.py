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
