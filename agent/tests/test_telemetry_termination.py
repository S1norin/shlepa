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


# --- F4: root-span input/output + final_ask spans --------------------------


def test_mark_input_stamps_root_span():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            telemetry.mark_input("Create hello.txt with the exact content hello")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    assert (
        roots[0].attributes.get("input.value")
        == "Create hello.txt with the exact content hello"
    )


def test_mark_outcome_stamps_status_and_output():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            telemetry.mark_outcome("done", "path: hello.txt")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("shlepa.status") == "done"
    assert attrs.get("output.value") == "path: hello.txt"


def test_mark_outcome_empty_output_sets_status_only():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            telemetry.mark_outcome("timeout", "")
    finally:
        provider.shutdown()

    roots = _root_spans(exporter)
    attrs = roots[0].attributes
    assert attrs.get("shlepa.status") == "timeout"
    assert "output.value" not in attrs


def test_mark_input_and_outcome_are_noops_outside_a_span():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        telemetry.mark_input("x")  # must not raise
        telemetry.mark_outcome("done", "y")  # must not raise
    finally:
        provider.shutdown()

    assert _root_spans(exporter) == []


def test_final_ask_span_carries_phase_prompt_and_outcome():
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        with telemetry.root_span(provider, task="t"):
            with telemetry.final_ask_span("work", "WRITE NOW", provider=provider) as span:
                assert span is not None
                span.set_attribute("shlepa.ok", True)
                span.set_attribute("output.value", "wrote it")
    finally:
        provider.shutdown()

    asks = [s for s in exporter.get_finished_spans() if s.name == "final_ask"]
    assert asks, f"no final_ask span; names: {[s.name for s in exporter.get_finished_spans()]}"
    attrs = asks[0].attributes
    assert attrs.get("shlepa.phase_id") == "work"
    assert attrs.get("input.value") == "WRITE NOW"
    assert attrs.get("shlepa.ok") is True
    assert attrs.get("output.value") == "wrote it"


def test_run_prompt_stamps_root_input_and_output(monkeypatch, stub_openai, tmp_path):
    """End-to-end: the root span carries the instruction and the final output."""
    import asyncio

    from stub_server import FINAL_ANSWER, PIPELINE_SCRIPT, stub_state

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
        # Mirror the entrypoint: the root span is opened by __main__, not by
        # run_prompt — the runner only stamps the already-open span.
        with telemetry.root_span(provider, task="contest-hello-file"):
            output = asyncio.run(run_prompt("Create hello.txt", instrument=True))
    finally:
        provider.shutdown()

    assert output == FINAL_ANSWER
    roots = _root_spans(exporter)
    assert roots, "no agent.run root span"
    attrs = roots[0].attributes
    assert attrs.get("input.value") == "Create hello.txt"
    assert attrs.get("shlepa.status") == "done"
    assert attrs.get("output.value") == FINAL_ANSWER
