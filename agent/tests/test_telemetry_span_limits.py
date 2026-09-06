"""Span attribute truncation: long attribute values (full tool stdout,
conversation message arrays) must be capped so exported traces stay small."""

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import telemetry  # noqa: E402


def _attribute_value(provider, exporter, value):
    """Record one span carrying the given attribute and return the stored value."""
    tracer = provider.get_tracer("attr-limit-test")
    with tracer.start_as_current_span("op") as span:
        span.set_attribute("big", value)
    provider.force_flush()  # BatchSpanProcessor exports on a delay
    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    return spans[0].attributes["big"]


def test_default_cap_truncates_long_values(monkeypatch):
    monkeypatch.delenv("SLEPA_OTEL_ATTR_LIMIT", raising=False)
    monkeypatch.delenv("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", raising=False)
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        value = _attribute_value(provider, exporter, "x" * 100_000)
    finally:
        provider.shutdown()
    assert len(value) == telemetry._DEFAULT_ATTR_LIMIT
    assert value == "x" * telemetry._DEFAULT_ATTR_LIMIT


def test_dev_knob_wins_over_default(monkeypatch):
    monkeypatch.delenv("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", raising=False)
    monkeypatch.setenv("SLEPA_OTEL_ATTR_LIMIT", "64")
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        value = _attribute_value(provider, exporter, "y" * 10_000)
    finally:
        provider.shutdown()
    assert value == "y" * 64


def test_otel_env_var_wins_over_dev_knob(monkeypatch):
    monkeypatch.setenv("SLEPA_OTEL_ATTR_LIMIT", "64")
    monkeypatch.setenv("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", "32")
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        value = _attribute_value(provider, exporter, "z" * 10_000)
    finally:
        provider.shutdown()
    assert value == "z" * 32


def test_short_values_untouched(monkeypatch):
    monkeypatch.delenv("SLEPA_OTEL_ATTR_LIMIT", raising=False)
    monkeypatch.delenv("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT", raising=False)
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        value = _attribute_value(provider, exporter, "short tool output")
    finally:
        provider.shutdown()
    assert value == "short tool output"
