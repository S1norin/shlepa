"""Telemetry-on test: spans captured when SLEPA_OTEL_ENABLED=1 (no collector needed)."""

import asyncio

import pytest

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("openinference.instrumentation.pydantic_ai")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import telemetry  # noqa: E402
from stub_server import FINAL_ANSWER, PIPELINE_SCRIPT, stub_state  # noqa: E402


def test_spans_captured_with_inmemory_exporter(monkeypatch, stub_openai, tmp_path):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
        monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
        monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))

        from shlepa_agent.runner import run_prompt

        stub_state["script"] = list(PIPELINE_SCRIPT)
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


def test_root_span_carries_task_attribute(monkeypatch, stub_openai, tmp_path):
    import sys

    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    monkeypatch.setattr(telemetry, "configure", lambda: provider)
    try:
        monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
        monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
        monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
        monkeypatch.setenv("SLEPA_TASK_SLUG", "contest-hello-file")
        monkeypatch.setattr(sys, "argv", ["shlepa_agent", "Create hello.txt"])
        stub_state["script"] = list(PIPELINE_SCRIPT)

        from shlepa_agent import __main__ as agent_main

        agent_main.main()
    finally:
        provider.shutdown()

    spans = exporter.get_finished_spans()
    roots = [s for s in spans if s.name == "agent.run"]
    assert roots, f"no agent.run root span; names: {[s.name for s in spans]}"
    assert roots[0].attributes.get("task") == "contest-hello-file"


def test_root_span_carries_shlepa_env_attributes(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        monkeypatch.setenv("SLEPA_BATCH_ID", "20260827T220000Z-abc123")
        monkeypatch.setenv("SLEPA_PRESET", "all")
        monkeypatch.setenv("SLEPA_GIT_SHA", "c75e065")
        monkeypatch.setenv("SLEPA_AGENT_VERSION", "0.3.0")
        with telemetry.root_span(provider, task="contest-hello-file"):
            pass
    finally:
        provider.shutdown()

    roots = [s for s in exporter.get_finished_spans() if s.name == "agent.run"]
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("task") == "contest-hello-file"
    assert attrs.get("shlepa.batch_id") == "20260827T220000Z-abc123"
    assert attrs.get("shlepa.preset") == "all"
    assert attrs.get("git.commit") == "c75e065"
    assert attrs.get("shlepa.agent_version") == "0.3.0"


def test_root_span_omits_unset_env_attributes(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        for var in ("SLEPA_BATCH_ID", "SLEPA_PRESET", "SLEPA_GIT_SHA", "SLEPA_AGENT_VERSION"):
            monkeypatch.delenv(var, raising=False)
        with telemetry.root_span(provider, task="contest-hello-file"):
            pass
    finally:
        provider.shutdown()

    roots = [s for s in exporter.get_finished_spans() if s.name == "agent.run"]
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert "shlepa.batch_id" not in attrs
    assert "shlepa.preset" not in attrs
    assert "git.commit" not in attrs
    assert "shlepa.agent_version" not in attrs


def test_is_enabled(monkeypatch):
    monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
    assert telemetry.is_enabled()
    monkeypatch.delenv("SLEPA_OTEL_ENABLED")
    assert not telemetry.is_enabled()
