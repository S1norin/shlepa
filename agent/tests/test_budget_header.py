"""w3-1: the budget header in every LLM request.

Every phase request (and the tool-less final_ask) carries a
``[phase=<id> elapsed=<s> remaining=<s>]`` line built from known
quantities only: the phase's own wall-clock cap and the monotonic
clock — never a guessed per-task deadline or token limit.
"""

import asyncio
import json
import logging

import pytest

from shlepa_agent.runner import _budget_header
from stub_server import stub_state


# -- unit tests -------------------------------------------------------------

def test_header_shape():
    out = _budget_header("plan", 42.7, 30.0, 5.2, "PROMPT")
    assert out.startswith("[phase=plan elapsed=43s remaining=25s]\n\nPROMPT")


def test_header_remaining_clamped_at_zero():
    out = _budget_header("work", 10.0, 30.0, 45.0, "PROMPT")
    assert "remaining=0s" in out
    assert out.endswith("PROMPT")


def test_header_no_cap_passthrough():
    assert _budget_header("plan", 1.0, None, 0.0, "PROMPT") == "PROMPT"


# -- e2e: the recorded request carries the header ---------------------------

@pytest.fixture
def events():
    from shlepa_agent.log import LOGGER

    records: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                records.append(json.loads(record.getMessage()))
            except (TypeError, ValueError):
                pass

    handler = _Collector()
    old_level = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)


def _run(monkeypatch, stub_openai, tmp_path, agent_cfg, task="t"):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    monkeypatch.delenv("SHLEPA_SALVAGE", raising=False)
    return asyncio.run(runner.run_prompt(task, agent_cfg=agent_cfg))


def test_every_phase_request_carries_the_header(
    monkeypatch, stub_openai, tmp_path, events
):
    from tests.test_snapshot import _cfg, _plan_step, _review_step, _work_step

    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _review_step("done"),
    ]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))

    bodies = [json.dumps(b) for b in stub_state["bodies"]]
    assert bodies, "no requests recorded"
    # plan, work and commit (review) requests all carry their header
    assert any("[phase=plan" in b for b in bodies)
    assert any("[phase=work" in b for b in bodies)
    assert any("[phase=commit" in b for b in bodies)
    # the header uses only known quantities
    assert "elapsed=" in bodies[0] and "remaining=" in bodies[0]
