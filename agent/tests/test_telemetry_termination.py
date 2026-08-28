"""Termination stamping on the agent.run root span (t10 span side)."""

import pytest

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("openinference.instrumentation.pydantic_ai")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402

from shlepa_agent import telemetry  # noqa: E402


def _root_spans(exporter):
    return [s for s in exporter.get_finished_spans() if s.name == "agent.run"]


def test_root_span_marks_crash_on_exception():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with pytest.raises(RuntimeError):
            with telemetry.root_span(provider, task="t"):
                raise RuntimeError("boom")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.termination_reason") == "crash"
    assert roots[0].status.status_code == StatusCode.ERROR


def test_root_span_ok_run_has_no_termination_reason():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            pass
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    assert "shlepa.termination_reason" not in roots[0].attributes


def test_mark_termination_stamps_current_span():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            telemetry.mark_termination("timeout")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.termination_reason") == "timeout"
    assert roots[0].status.status_code == StatusCode.ERROR


def test_specific_termination_stamp_survives_root_context():
    """An entrypoint stamps 'crash:<Exc>' via mark_termination, then the
    exception propagates out of root_span; the specific reason must not
    be clobbered by the generic 'crash' fallback."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with pytest.raises(RuntimeError):
            with telemetry.root_span(provider, task="t"):
                telemetry.mark_termination("crash:BoomError")
                raise RuntimeError("boom")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    assert roots[0].attributes.get("shlepa.termination_reason") == "crash:BoomError"


def test_mark_termination_is_a_noop_without_active_span():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        telemetry.mark_termination("timeout")  # must not raise
    finally:
        provider.shutdown()

    assert _root_spans(exporter) == []
