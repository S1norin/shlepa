"""TrackedModel (v5): per-request caps from config, usage logged.

There is NO task time limit T, NO hard stop and NO request gate in the
model: the only bounds are the per-request open timeout (config) and the
fixed llm wall (budget.LLM_WALL). Tokens are counted and logged only.
"""

import asyncio
import json
import logging

from stub_server import FINAL_ANSWER, reset_stub_state, stub_state

REASONING = "THINK-" * 4000  # 20000 chars > MAX_LOG_VALUE_CHARS (16000)


def _write_cfg(tmp_path) -> None:
    toml_path = tmp_path / "cfg.toml"
    toml_path.write_text(
        """
[agent]
temp = 0.1

[budget]
max_tokens = 1234
request_timeout = 7.5

[phases.plan]
tools = ["bash"]
requests = 5
""",
        encoding="utf-8",
    )


def _make_model(tmp_path):
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel

    _write_cfg(tmp_path)
    return TrackedModel(
        "stub-model",
        OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"),
        load_config(tmp_path / "cfg.toml"),
    )


def test_tracked_model_caps_from_config(tmp_path):
    from shlepa_agent.budget import LLM_WALL

    model = _make_model(tmp_path)
    # Per-request open timeout comes from [budget]; the llm wall is the
    # fixed regime constant.
    assert model.request_timeout == 7.5
    assert model.llm_wall == LLM_WALL
    assert model._capped_settings({})["max_tokens"] == 1234
    # The cap is applied to a fresh copy, never to the caller's dict.
    ms = {}
    model._capped_settings(ms)
    assert ms == {}


def test_token_usage_counted_but_not_limited(tmp_path, monkeypatch):
    """v5: token usage is accumulated and logged (tie-break analysis) but
    never limits requests — no token budget exists."""
    import shlepa_agent.model as model_mod

    model = _make_model(tmp_path)
    model._cum_input = 2_900_000  # far past any old budget
    model._cum_output = 10_000

    async def fake_super(self, messages, ms, params):
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    assert asyncio.run(model.request([], {}, None)) == "ok"


def _pending(model, usage) -> None:
    from types import SimpleNamespace

    model._pending_stream = SimpleNamespace(usage=usage)


def _capture_events(model):
    """Log one pending usage and return the parsed 'usage' event dict."""
    import json

    from shlepa_agent.log import LOGGER

    records: list[str] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Collector()
    old_level = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        model.log_pending_usage()
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)
    for line in records:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if payload.get("event") == "usage":
            return payload
    raise AssertionError(f"no usage event captured; got: {records}")


def test_usage_event_carries_cache_and_reasoning(tmp_path):
    """usage events expose cache_read/cache_write and (when reported)
    reasoning tokens; 0 when the endpoint doesn't report them."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    _pending(model, RequestUsage(
        input_tokens=1000, output_tokens=100,
        cache_read_tokens=100, cache_write_tokens=50,
        details={"reasoning_tokens": 77},
    ))
    event = _capture_events(model)
    assert event["input_tokens"] == 1000
    assert event["output_tokens"] == 100
    assert event["cache_read_tokens"] == 100
    assert event["cache_write_tokens"] == 50
    assert event["reasoning_tokens"] == 77


def test_usage_event_no_cache_reports_zero(tmp_path):
    """Endpoints without cache reporting: cache fields are present, zero."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    _pending(model, RequestUsage(input_tokens=42, output_tokens=7))
    event = _capture_events(model)
    assert event["cache_read_tokens"] == 0
    assert event["cache_write_tokens"] == 0
    assert "reasoning_tokens" not in event  # absent, not zero-padded


def test_usage_cumulative_cache_accumulates(tmp_path):
    """Cumulative cache fields accumulate across requests like
    cumulative_input/cumulative_output."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    _pending(model, RequestUsage(
        input_tokens=1000, output_tokens=100,
        cache_read_tokens=100, cache_write_tokens=50,
    ))
    first = _capture_events(model)
    _pending(model, RequestUsage(
        input_tokens=2000, output_tokens=200,
        cache_read_tokens=150, cache_write_tokens=25,
    ))
    second = _capture_events(model)
    assert first["cumulative_input"] == 1000
    assert first["cumulative_cache_read"] == 100
    assert first["cumulative_cache_write"] == 50
    assert second["cumulative_input"] == 3000
    assert second["cumulative_output"] == 300
    assert second["cumulative_cache_read"] == 250
    assert second["cumulative_cache_write"] == 75


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
    # plan (with thinking) -> trivial review: the thinking event comes from
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
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "status": "ok",
                    "artifact": "hello.txt",
                    "checks": ["re-read -> matches"],
                    "notes": FINAL_ANSWER,
                },
            }
        },
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


# -- per-phase usage tagging (issue #73) ------------------------------------


def test_usage_event_carries_current_phase(tmp_path):
    """usage events are tagged with the model's current phase (per-phase
    token attribution for the CLI). Issue #73."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    model.current_phase = "plan"
    _pending(model, RequestUsage(input_tokens=100, output_tokens=10))
    event = _capture_events(model)
    assert event["phase"] == "plan"


def test_usage_event_phase_rotates_across_runs(tmp_path):
    """Rotating the phase between log calls updates subsequent events
    (plan -> work). Issue #73."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    model.current_phase = "plan"
    _pending(model, RequestUsage(input_tokens=100, output_tokens=10))
    first = _capture_events(model)
    model.current_phase = "work"
    _pending(model, RequestUsage(input_tokens=200, output_tokens=20))
    second = _capture_events(model)
    assert first["phase"] == "plan"
    assert second["phase"] == "work"


def test_usage_event_without_phase_has_no_phase_field(tmp_path):
    """Usages logged before any phase is set carry no phase field (no
    crash, legacy consumers unaffected). Issue #73."""
    from pydantic_ai.usage import RequestUsage

    model = _make_model(tmp_path)
    _pending(model, RequestUsage(input_tokens=42, output_tokens=7))
    event = _capture_events(model)
    assert "phase" not in event
