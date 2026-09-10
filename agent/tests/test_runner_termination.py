"""termination_reason stamps on the agent.run root span (#127).

The runner stamps first-class termination reasons via mark_termination
on every exit path: the step guard (``budget``), the final-cycle exit
gate (``timeout`` / ``error``, the latter covering LLM-error exhaustion
surfacing as a phase error), and the commit fallback (``no_verdict``).
``endpoint_finalized`` (w3-5) and the ``crash`` stamps predate this
module and are pinned here too. Phase results are scripted — no LLM
calls, no stub server.
"""

import asyncio

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from shlepa_agent import runner, telemetry  # noqa: E402
from shlepa_agent.config import load_config  # noqa: E402
from shlepa_agent.phases.base import PhaseResult, RunState  # noqa: E402
from shlepa_agent.tools import AgentDeps  # noqa: E402


class _FakeModel:
    """Just enough surface for _pipeline (elapsed clock, no endpoint
    counter so _model_endpoint_stalled degrades to False)."""

    endpoint_failure_count = 0

    def elapsed(self) -> float:
        return 0.0


class _FakePhase:
    """phase_factory stand-in: _pipeline only reads .id (the phase run
    itself is scripted)."""

    def __init__(self, phase_id: str):
        self.id = phase_id


def _make_state(tmp_path, monkeypatch) -> RunState:
    monkeypatch.setenv("SHLEPA_STATE_FILE", str(tmp_path / "state.json"))
    model = _FakeModel()
    return RunState(
        task="test task",
        deps=AgentDeps(workdir=tmp_path, cfg=load_config(), clock=model.elapsed),
        model=model,
    )


def _run_pipeline(
    monkeypatch,
    tmp_path,
    provider,
    script: list[PhaseResult],
    max_cycles: int,
    max_steps: int | None = None,
) -> tuple[str, str]:
    """Drive _pipeline with scripted phase results under a root span."""
    monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
    monkeypatch.setenv("SHLEPA_MAX_CYCLES", str(max_cycles))
    if max_steps is not None:
        monkeypatch.setenv("SHLEPA_MAX_STEPS", str(max_steps))
    else:
        monkeypatch.delenv("SHLEPA_MAX_STEPS", raising=False)
    state = _make_state(tmp_path, monkeypatch)

    queue = list(script)

    async def _fake_run_phase(state_, phase, instrument, cycle=1):
        res = queue.pop(0) if queue else PhaseResult(status="done")
        state_.results[phase.id] = res
        return res

    async def _no_final_ask(state_, phase):
        pass

    monkeypatch.setattr(runner, "_run_phase_with_retries", _fake_run_phase)
    monkeypatch.setattr(runner, "_final_ask", _no_final_ask)

    with telemetry.root_span(provider, task="test-task"):
        return asyncio.run(
            runner._pipeline(
                state, True, _FakePhase, "plan", max_steps
            )
        )


def _termination_reason(exporter):
    roots = [s for s in exporter.get_finished_spans() if s.name == "agent.run"]
    assert roots, "no agent.run root span"
    return roots[0].attributes.get("shlepa.termination_reason")


def test_step_guard_stamps_budget(monkeypatch, tmp_path):
    """The dev-knob step guard aborts between cycles with reason 'budget'."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        script = [
            PhaseResult(status="done", summary="plan 1"),
            PhaseResult(status="done", summary="work 1"),
            PhaseResult(status="done", summary="review 1"),
        ]
        # max_cycles=3 so the guard (steps=1 >= max_steps=1, cycle=2 < 3)
        # fires before the final-cycle exit gate.
        status, _ = _run_pipeline(
            monkeypatch, tmp_path, provider, script,
            max_cycles=3, max_steps=1,
        )
    finally:
        provider.shutdown()
    assert status == "timeout"
    assert _termination_reason(exporter) == "budget"


def test_final_cycle_timeout_stamps_timeout(monkeypatch, tmp_path):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        script = [
            PhaseResult(status="done", summary="plan 1"),
            PhaseResult(status="timeout", error="work time cap reached"),
        ]
        status, _ = _run_pipeline(
            monkeypatch, tmp_path, provider, script, max_cycles=1,
        )
    finally:
        provider.shutdown()
    assert status == "timeout"
    assert _termination_reason(exporter) == "timeout"


def test_final_cycle_error_stamps_error(monkeypatch, tmp_path):
    """A final-cycle phase error (LLM-error exhaustion after the model's
    own retries) ends the run with reason 'error'."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        script = [
            PhaseResult(status="done", summary="plan 1"),
            PhaseResult(
                status="error", error="ModelAPIError: model request failed"
            ),
        ]
        status, _ = _run_pipeline(
            monkeypatch, tmp_path, provider, script, max_cycles=1,
        )
    finally:
        provider.shutdown()
    assert status == "error"
    assert _termination_reason(exporter) == "error"


def test_done_run_carries_no_termination_reason(monkeypatch, tmp_path):
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    try:
        script = [
            PhaseResult(status="done", summary="plan 1"),
            PhaseResult(status="done", summary="work 1"),
        ]
        status, _ = _run_pipeline(
            monkeypatch, tmp_path, provider, script, max_cycles=1,
        )
    finally:
        provider.shutdown()
    assert status == "done"
    assert _termination_reason(exporter) is None


def test_commit_fallback_stamps_no_verdict(monkeypatch, tmp_path):
    """A verify/commit pass that ended without a verdict stamps
    'no_verdict' (dead under the hard-cycle regime; pinned for the
    phase re-enable)."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    monkeypatch.setenv("SLEPA_OTEL_ENABLED", "1")
    state = _make_state(tmp_path, monkeypatch)
    try:
        with telemetry.root_span(provider, task="test-task"):
            runner._commit_fallback_hints(
                state, {"valid": False, "reason": "missing: answer.txt"}
            )
    finally:
        provider.shutdown()
    assert _termination_reason(exporter) == "no_verdict"
    commit = state.results["commit"]
    assert commit.status == "timeout"
    assert commit.output.done is False
    assert any(
        "mechanical deliverable check" in p for p in commit.output.problems
    )


def test_endpoint_finalized_still_stamped(monkeypatch, tmp_path):
    """w3-5 endpoint stall keeps stamping 'endpoint_finalized' (kept,
    not replaced, by #127)."""
    exporter = InMemorySpanExporter()
    provider = telemetry.configure(exporter=exporter)
    monkeypatch.setattr(runner, "_model_endpoint_stalled", lambda state: True)
    try:
        script = [PhaseResult(status="done", summary="plan 1")]
        status, _ = _run_pipeline(
            monkeypatch, tmp_path, provider, script, max_cycles=1,
        )
    finally:
        provider.shutdown()
    assert status == "done"
    assert _termination_reason(exporter) == "endpoint_finalized"
