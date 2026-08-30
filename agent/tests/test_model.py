"""t4: TrackedModel budgets come from the v2 agent config; thinking is logged.

Unit: TrackedModel reads hard/soft/timeout/wall/max_tokens from [budget].
Integration (stub): a reasoning_content answer produces an llm_thinking event
with the FULL thinking text (no truncation).
"""

import asyncio
import json
import logging

import pytest

from stub_server import FINAL_ANSWER, reset_stub_state, stub_state

REASONING = "THINK-" * 4000  # 20000 chars > MAX_LOG_VALUE_CHARS (16000)


def test_tracked_model_budgets_from_v2_config(tmp_path):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        """
[agent]
temp = 0.42

[budget]
hard_time = 111.0
soft_time = 99.0
request_timeout = 7.5
request_wall = 88.0
max_tokens = 1234

[phases.plan]
tools = ["bash"]
requests = 5
time = 100.0
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from pydantic_ai.providers.openai import OpenAIProvider

    agent_cfg = load_config(toml_path)
    model = TrackedModel(
        "stub-model", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), agent_cfg
    )
    assert model.cfg.hard_time == 111.0
    assert model.cfg.soft_time == 99.0
    assert model.cfg.request_timeout == 7.5
    assert model.cfg.request_wall == 88.0
    assert model._capped_settings({})["max_tokens"] == 1234


def _make_model(tmp_path, hard_time: float, soft_time: float):
    toml_path = tmp_path / "cfg.toml"
    toml_path.write_text(
        f"""
[agent]
temp = 0.1

[budget]
hard_time = {hard_time}
soft_time = {soft_time}

[phases.plan]
tools = ["bash"]
requests = 5
time = 50.0
""",
        encoding="utf-8",
    )
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel

    return TrackedModel(
        "stub-model",
        OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"),
        load_config(toml_path),
    )


def test_soft_time_is_advisory(tmp_path, monkeypatch):
    """A request past the soft boundary must NOT raise; only hard raises."""
    import shlepa_agent.model as model_mod

    model = _make_model(tmp_path, hard_time=100.0, soft_time=10.0)
    model.t0 -= 50.0  # elapsed 50s: past soft (10s), under hard (100s)

    async def fake_super(self, messages, ms, params):
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    assert asyncio.run(model.request([], {}, None)) == "ok"


def test_hard_time_still_raises(tmp_path):
    """The global hard backstop must still raise BudgetExceeded."""
    from shlepa_agent.model import BudgetExceeded

    model = _make_model(tmp_path, hard_time=100.0, soft_time=10.0)
    model.t0 -= 200.0  # elapsed 200s: past hard (100s)
    with pytest.raises(BudgetExceeded):
        asyncio.run(model.request([], {}, None))


def _run(monkeypatch, stub_openai, tmp_path, task="Create hello.txt with the exact content hello"):
    from shlepa_agent.runner import run_prompt

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(run_prompt(task))


def test_llm_thinking_event_carries_full_text(monkeypatch, stub_openai, tmp_path):
    from shlepa_agent.log import LOGGER
    from shlepa_agent.log import MAX_LOG_VALUE_CHARS

    assert len(REASONING) > MAX_LOG_VALUE_CHARS

    reset_stub_state()
    # plan (with thinking) -> trivial commit: the thinking event comes from
    # the plan phase's single final_result request.
    stub_state["script"] = [
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "goal": "write hello.txt with the content hello",
                    "findings": "",
                    "steps": ["write the file"],
                    "decision": "commit",
                },
            },
            "reasoning": REASONING,
        },
        {"final": FINAL_ANSWER},
    ]

    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Collector()
    old_level = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)  # decouple from _configure_logging() ordering
    try:
        _run(monkeypatch, stub_openai, tmp_path)
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)

    events = [
        json.loads(line)
        for line in records
        if line.strip().startswith("{") and json.loads(line).get("event") == "llm_thinking"
    ]
    assert len(events) == 1, f"expected one llm_thinking event, got {len(events)}"
    assert events[0]["content"] == REASONING
    assert "... [output truncated" not in events[0]["content"]
