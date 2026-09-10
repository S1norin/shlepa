"""Span flush discipline (#126).

The docker-exec hard timeout kills the agent process with SIGKILL, which
runs no atexit/SIGTERM handler. The only way finished spans survive a kill
is to force-flush them while the process is still alive: after every
finished LLM span (short window) and on every run exit path (long window).
These tests pin that behavior.
"""

import os
import signal

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import telemetry  # noqa: E402


def test_flush_spans_is_a_noop_without_provider(monkeypatch):
    monkeypatch.setattr(telemetry, "_PROVIDER", None)
    telemetry.flush_spans()  # must not raise (baseline / unconfigured)


def test_flush_spans_delegates_to_configured_provider(monkeypatch):
    calls = []

    class _StubProvider:
        def force_flush(self, timeout_millis):
            calls.append(timeout_millis)

    monkeypatch.setattr(telemetry, "_PROVIDER", _StubProvider())
    telemetry.flush_spans(1234)
    assert calls == [1234]
    telemetry.flush_spans()  # default window
    assert calls == [1234, telemetry._EXIT_FLUSH_MILLIS]


def test_configure_stores_provider_for_flush():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        assert telemetry._PROVIDER is provider
    finally:
        provider.shutdown()


def test_llm_span_is_flushed_immediately_on_end():
    """A finished LLM span must leave the process without waiting for the
    5 s batch schedule — a SIGKILL right after the last LLM call must not
    lose it."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        tracer = provider.get_tracer("t")
        with tracer.start_as_current_span("llm call") as span:
            span.set_attribute("llm.token_count.prompt", 10)
            span.set_attribute("llm.token_count.completion", 5)
        # The on_end hook force-flushed the span; it is already at the
        # exporter although the batch delay (5 s) has not elapsed.
        assert [s.name for s in exporter.get_finished_spans()] == ["llm call"]
    finally:
        provider.shutdown()


def test_non_llm_span_is_not_flushed_on_end():
    """Spans without LLM usage do not trigger a flush on end; they ride
    the batch schedule (5 s), so a fresh exporter is still empty here."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        tracer = provider.get_tracer("t")
        with tracer.start_as_current_span("plain tool span"):
            pass
        assert not exporter.get_finished_spans()
    finally:
        provider.shutdown()


def test_flush_spans_exports_queued_spans():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        tracer = provider.get_tracer("t")
        with tracer.start_as_current_span("queued"):
            pass
        assert not exporter.get_finished_spans()
        telemetry.flush_spans()
        assert [s.name for s in exporter.get_finished_spans()] == ["queued"]
    finally:
        provider.shutdown()


def test_mark_termination_triggers_exit_flush(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    calls = []
    monkeypatch.setattr(telemetry, "flush_spans", lambda ms: calls.append(ms))
    try:
        with telemetry.root_span(provider, task="t"):
            telemetry.mark_termination("timeout")
    finally:
        provider.shutdown()
    # One flush for the termination stamp, one for the root span exit.
    assert calls == [telemetry._EXIT_FLUSH_MILLIS, telemetry._EXIT_FLUSH_MILLIS]


def test_root_span_exit_triggers_flush_on_both_paths(monkeypatch):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    calls = []
    monkeypatch.setattr(telemetry, "flush_spans", lambda ms: calls.append(ms))
    try:
        with telemetry.root_span(provider, task="t"):
            pass
        assert calls == [telemetry._EXIT_FLUSH_MILLIS]

        calls.clear()
        with pytest.raises(RuntimeError):
            with telemetry.root_span(provider, task="t"):
                raise RuntimeError("boom")
    finally:
        provider.shutdown()
    assert calls == [telemetry._EXIT_FLUSH_MILLIS]


def test_configure_installs_sigterm_flush_handler(monkeypatch):
    """configure() installs a SIGTERM handler that flushes, restores the
    default disposition, and re-kills itself — death semantics unchanged."""
    exporter = InMemorySpanExporter()
    telemetry.configure(exporter=exporter)
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler), "SIGTERM handler not installed"

    calls = []
    killed = []
    monkeypatch.setattr(telemetry, "flush_spans", lambda ms: calls.append(ms))
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))

    handler(signal.SIGTERM, None)

    assert calls == [telemetry._EXIT_FLUSH_MILLIS]
    assert killed == [(os.getpid(), signal.SIGTERM)]
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL
