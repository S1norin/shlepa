"""Telemetry-on test: spans captured when SLEPA_OTEL_ENABLED=1 (no collector needed)."""

import asyncio

import pytest

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("openinference.instrumentation.pydantic_ai")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import telemetry  # noqa: E402
from stub_server import FINAL_ANSWER  # noqa: E402


def test_spans_captured_with_inmemory_exporter(monkeypatch, stub_openai, tmp_path):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
        monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
        monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))

        from shlepa_agent.core import run_prompt

        output = asyncio.run(run_prompt("Create hello.txt", instrument=True))
    finally:
        provider.shutdown()

    assert output == FINAL_ANSWER
    spans = exporter.get_finished_spans()
    assert spans, "no spans captured"
    gen_ai = [
        s
        for s in spans
        if "gen_ai.request.model" in (s.attributes or {})
        or "gen_ai.operation.name" in (s.attributes or {})
    ]
    assert gen_ai, f"no gen_ai.* spans; names: {[s.name for s in spans]}"


def test_is_enabled(monkeypatch):
    monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
    assert telemetry.is_enabled()
    monkeypatch.delenv("SLEPA_OTEL_ENABLED")
    assert not telemetry.is_enabled()
