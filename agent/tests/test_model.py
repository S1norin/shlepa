"""t4: TrackedModel budgets come from the v2 agent config; thinking is logged.

Unit: TrackedModel reads hard/soft/timeout/wall/max_tokens from [budget].
Integration (stub): a reasoning_content answer produces an llm_thinking event
with the FULL thinking text (no truncation).
"""

import asyncio
import json
import logging

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

[phases.explore]
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
    stub_state["script"] = [{"final": FINAL_ANSWER, "reasoning": REASONING}]

    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Collector()
    LOGGER.addHandler(handler)
    try:
        _run(monkeypatch, stub_openai, tmp_path)
    finally:
        LOGGER.removeHandler(handler)

    events = [
        json.loads(line)
        for line in records
        if line.strip().startswith("{") and json.loads(line).get("event") == "llm_thinking"
    ]
    assert len(events) == 1, f"expected one llm_thinking event, got {len(events)}"
    assert events[0]["content"] == REASONING
    assert "... [output truncated" not in events[0]["content"]
