"""TrackedModel (v5): per-request caps from config, usage logged.

There is NO task time limit T, NO hard stop and NO request gate in the
model: the only bounds are the per-request open timeout (config) and the
fixed llm wall (budget.LLM_WALL). Tokens are counted and logged only.
"""

import asyncio
import json
import logging

import pytest

from stub_server import FINAL_ANSWER, reset_stub_state, stub_state

REASONING = "THINK-" * 4000  # 20000 chars > MAX_LOG_VALUE_CHARS (16000)


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


# -- w3-5: endpoint failures (429/402/5xx storm) ---------------------------

def test_endpoint_failure_counter_and_stall(tmp_path):
    model = _make_model(tmp_path)
    assert model.cfg.endpoint_fail_limit == 3  # default
    assert not model.endpoint_stalled
    model.note_endpoint_failure(429)
    model.note_endpoint_failure(402)
    model.note_endpoint_failure(400)  # non-terminal: ignored
    assert model.endpoint_failure_count == 2
    assert not model.endpoint_stalled
    model.note_endpoint_failure(503)
    assert model.endpoint_stalled
    model.note_endpoint_success()
    assert model.endpoint_failure_count == 0
    assert not model.endpoint_stalled


def test_endpoint_stall_limit_from_config(tmp_path):
    toml_path = tmp_path / "cfg1.toml"
    toml_path.write_text(
        """
[agent]
temp = 0.1

[budget]
endpoint_fail_limit = 1

[phases.plan]
tools = ["bash"]
requests = 5
""",
        encoding="utf-8",
    )
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel

    model = TrackedModel(
        "stub-model",
        OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"),
        load_config(toml_path),
    )
    model.note_endpoint_failure(429)
    assert model.endpoint_stalled


def test_endpoint_storm_finalizes_run(monkeypatch, stub_openai, tmp_path, events):
    """AC: consecutive 429s -> endpoint_finalized, no further requests,
    the deliverable stays on disk, the run ends "done" (exit 0)."""
    from stub_server import reset_stub_state

    reset_stub_state()
    stub_state["script"] = [
        {
            "tool_call": {
                "name": "final_result",
                "arguments": {
                    "goal": "write out.json with the answer",
                    "findings": "",
                    "steps": ["write the file"],
                },
            }
        },
        {
            "tool_call": {
                "name": "write",
                "arguments": {"path": "out.json", "text": '{"answer": 42}'},
            }
        },
        {"error": 429},  # work (2nd request of the phase) -> #1
        {"error": 429},  # work-timeout final_ask -> #2
        {"error": 429},  # review relay -> #3 -> stalled -> finalize
    ]
    out = _run(monkeypatch, stub_openai, tmp_path)

    # the deliverable is on disk and the run ends normally
    assert (tmp_path / "out.json").read_text() == '{"answer": 42}'
    assert isinstance(out, str)

    ev = {(e.get("event"), e.get("phase")): e for e in events if isinstance(e, dict)}
    errors = [e for e in events if e.get("event") == "endpoint_error"]
    assert [e["consecutive"] for e in errors] == [1, 2, 3]
    assert all(e["status"] == 429 for e in errors)

    assert ev.get(("endpoint_stalled", "review"), {}).get("failures") == 3
    fin = [e for e in events if e.get("event") == "endpoint_finalized"]
    assert fin and fin[0]["failures"] == 3

    done = [e for e in events if e.get("event") == "agent_done"]
    assert done and done[-1]["status"] == "done"

    # exactly one count per AGENT request (the openai SDK retries each 429
    # a few times on the wire, so raw bodies > agent requests):
    assert len(stub_state["bodies"]) >= 5

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


def test_nonstream_retry_usage_is_counted_once(tmp_path, monkeypatch):
    """Failed attempts stay visible without duplicating the successful response usage."""
    from types import SimpleNamespace
    from pydantic_ai.usage import RequestUsage
    import shlepa_agent.model as model_mod

    model = _make_model(tmp_path)
    calls = 0
    events = []

    async def fake_super(self, messages, ms, params):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError("request timed out")
        return SimpleNamespace(usage=RequestUsage(input_tokens=10, output_tokens=7,
                                                  details={"reasoning_tokens": 0}))

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    monkeypatch.setattr(model_mod, "_log_event", lambda event, **data: events.append((event, data)))
    asyncio.run(model.request([], {}, None))
    model.log_pending_usage()
    names = [name for name, _ in events]
    assert names.count("llm_request") == 2
    assert names.count("llm_error") == names.count("llm_retry") == 1
    assert names.count("usage") == 1
    usage = next(data for name, data in events if name == "usage")
    assert usage["cumulative_input"] == 10 and usage["cumulative_output"] == 7
    assert usage["reasoning_tokens"] == 0


# -- endpoint preflight + adaptive max_tokens (checkpoint 0-score fix) --------
#
# Contest checkpoints expose an unknown OpenAI-compatible endpoint. A
# max_tokens larger than its output cap rejects every request with 400,
# which scored 0 on every task. The preflight probe discovers the working
# cap before the first phase; a mid-run cap rejection retries with a halved
# cap.


def test_max_tokens_error_detection():
    from shlepa_agent.model import _looks_like_max_tokens_error

    # Output-cap rejections
    assert _looks_like_max_tokens_error(400, "max_tokens 16384 exceeds the maximum of 8192")
    assert _looks_like_max_tokens_error(400, "Invalid max_output_tokens: must be <= 4096")
    assert _looks_like_max_tokens_error(400, "Requested 16384 output tokens; model supports 8192")
    # Context/prompt/input framing is a context overflow, not an output cap
    assert not _looks_like_max_tokens_error(400, "maximum context length of 32768 exceeded")
    assert not _looks_like_max_tokens_error(400, "prompt is too long: 200000 tokens")
    assert not _looks_like_max_tokens_error(400, "invalid input format")
    # Non-400 is never an output-cap rejection
    assert not _looks_like_max_tokens_error(429, "max_tokens exceeds maximum")
    assert not _looks_like_max_tokens_error(500, "max_output_tokens invalid")


def test_try_reduce_max_tokens_halves_and_floors(tmp_path):
    model = _make_model(tmp_path)
    ms = {"max_tokens": 16384}
    assert model._try_reduce_max_tokens(400, "max_tokens exceeds maximum", ms) is True
    assert ms["max_tokens"] == 8192
    assert model.effective_max_tokens == 8192
    # At the floor: no further reduction
    assert (
        model._try_reduce_max_tokens(400, "max_tokens exceeds maximum", {"max_tokens": 2048})
        is False
    )
    # Non-cap bodies and non-400: untouched
    assert model._try_reduce_max_tokens(400, "boom", {"max_tokens": 8192}) is False
    assert (
        model._try_reduce_max_tokens(
            429, "max_tokens exceeds maximum", {"max_tokens": 8192}
        )
        is False
    )
    assert (
        model._try_reduce_max_tokens(
            400, "max_tokens exceeds maximum", {"max_tokens": 1000}
        )
        is False
    )


def test_capped_settings_uses_discovered_cap(tmp_path):
    model = _make_model(tmp_path)
    assert model._capped_settings({})["max_tokens"] == 1234  # cfg default
    model.effective_max_tokens = 4096
    assert model._capped_settings({})["max_tokens"] == 4096
    # Discovered 0 = send no max_tokens at all (endpoint default applies)
    model.effective_max_tokens = 0
    assert "max_tokens" not in model._capped_settings({})
    # An explicit caller cap always wins
    model.effective_max_tokens = 4096
    assert model._capped_settings({"max_tokens": 999})["max_tokens"] == 999


def test_preflight_probes_no_cap_first_and_prefers_accepted_cap(
    tmp_path, monkeypatch
):
    """AC: the no-cap request is probed first (the only shape an earlier
    checkpoint in this contest accepted); when the endpoint ALSO accepts a
    capped probe, the cap wins (bounds output, predictable timing)."""
    model = _make_model(tmp_path)
    calls: list[int | None] = []

    async def fake_probe(ms):
        calls.append(ms.get("max_tokens"))  # endpoint accepts everything

    monkeypatch.setattr(model, "_probe_stream", fake_probe)
    assert asyncio.run(model.preflight()) is True
    assert calls[0] is None  # no-cap probed first
    assert model.effective_max_tokens == model.cfg.max_tokens


def test_preflight_uses_no_cap_when_caps_rejected(tmp_path, monkeypatch):
    """AC: when the endpoint rejects capped requests (any non-cap error),
    the preflight falls back to the no-cap shape -- the only shape an
    earlier checkpoint scored with."""
    from pydantic_ai.exceptions import ModelHTTPError

    model = _make_model(tmp_path)
    calls: list[int | None] = []

    async def fake_probe(ms):
        calls.append(ms.get("max_tokens"))
        if "max_tokens" in ms:
            raise ModelHTTPError(
                400,
                "stub-model",
                {"error": {"message": "Unknown field: max_tokens"}},
            )

    monkeypatch.setattr(model, "_probe_stream", fake_probe)
    assert asyncio.run(model.preflight()) is True
    assert calls[0] is None  # no-cap probed first
    assert model.effective_max_tokens == 0  # no max_tokens sent in-run


def test_preflight_discovers_max_tokens_cap(tmp_path, monkeypatch):
    from shlepa_agent.model import _MaxTokensRejected

    model = _make_model(tmp_path)
    calls: list[int | None] = []

    async def fake_probe(ms):
        cap = ms.get("max_tokens")
        calls.append(cap)
        if cap is None or cap != 2048:
            raise _MaxTokensRejected(max(2048, (cap or 0) // 2))

    monkeypatch.setattr(model, "_probe_stream", fake_probe)
    assert asyncio.run(model.preflight()) is True
    assert calls[0] is None  # no-cap probed first, then the cap ladder
    assert model.effective_max_tokens == 2048


def test_preflight_probes_real_stream(stub_openai, tmp_path, events):
    """AC: preflight issues a real streaming probe through the production
    path and logs endpoint_preflight with ok=true (regression: a raw prompt
    tuple instead of a ModelRequest hit an assert_never in pydantic-ai)."""
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel

    _write_cfg(tmp_path)
    model = TrackedModel(
        "stub-model",
        OpenAIProvider(base_url=stub_openai, api_key="k"),
        load_config(tmp_path / "cfg.toml"),
    )
    assert asyncio.run(model.preflight()) is True
    # The stub accepts both shapes; the accepted cap wins.
    assert model.effective_max_tokens == model.cfg.max_tokens
    pre = [e for e in events if e.get("event") == "endpoint_preflight"]
    assert pre and pre[-1]["ok"] is True
    assert pre[-1]["max_tokens"] == model.cfg.max_tokens


def test_preflight_all_probes_rejected_fails(tmp_path, monkeypatch):
    from shlepa_agent.model import _MaxTokensRejected

    model = _make_model(tmp_path)
    calls: list[int | None] = []

    async def fake_probe(ms):
        calls.append(ms.get("max_tokens"))
        raise _MaxTokensRejected(2048)

    monkeypatch.setattr(model, "_probe_stream", fake_probe)
    assert asyncio.run(model.preflight()) is False
    assert calls[0] is None  # no-cap probed first
    # The last reduced cap was itself rejected: not retained.
    assert model.effective_max_tokens is None


def test_preflight_failure_logs_and_returns_false(tmp_path, monkeypatch):
    model = _make_model(tmp_path)

    async def fake_probe(ms):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(model, "_probe_stream", fake_probe)
    assert asyncio.run(model.preflight()) is False
    assert model.effective_max_tokens is None  # run proceeds with cfg default


def test_request_retries_with_reduced_cap_on_400(tmp_path, monkeypatch):
    from pydantic_ai.exceptions import ModelHTTPError

    import shlepa_agent.model as model_mod

    model = _make_model(tmp_path)
    model.effective_max_tokens = 8192  # e.g. discovered by preflight
    calls: list[int] = []

    async def fake_super(self, messages, ms, params):
        calls.append(int((ms or {}).get("max_tokens") or 0))
        if (ms or {}).get("max_tokens", 0) > 4096:
            raise ModelHTTPError(
                400,
                "stub-model",
                {"error": {"message": "max_tokens 8192 exceeds maximum of 4096"}},
            )
        return "ok"

    monkeypatch.setattr(model_mod.OpenAIChatModel, "request", fake_super)
    assert asyncio.run(model.request([], {}, None)) == "ok"
    assert calls == [8192, 4096]
    assert model.effective_max_tokens == 4096
