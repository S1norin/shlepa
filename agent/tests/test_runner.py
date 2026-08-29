"""t6: runner tests — phase-graph execution, budget routing, retries, log contract.

The runner (shlepa_agent.runner) walks the configured phase graph:
entry phase -> PhaseResult -> route() -> next phase, with a step guard,
per-phase error retries, and the emergency phase as the last line of defense.
"""

import asyncio
import json
import logging

import pytest

from stub_server import FINAL_ANSWER, stub_state


@pytest.fixture
def events():
    """Collect agent JSON log events for the duration of a test."""
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
    LOGGER.setLevel(logging.INFO)  # decouple from _configure_logging() ordering
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)


def _run(monkeypatch, stub_openai, tmp_path, agent_cfg=None, task="create hello.txt"):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(runner.run_prompt(task, agent_cfg=agent_cfg))


def test_main_never_crashes_on_env_failure(monkeypatch, events):
    # Missing LLM endpoint env: run_prompt must log agent_error + a final
    # agent_done(status=error) and main() must return (process exits 0).
    from shlepa_agent import runner

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    import sys

    monkeypatch.setattr(sys, "argv", ["shlepa_agent", "some task"])
    runner.main()  # must not raise
    assert any(e.get("event") == "agent_error" for e in events)
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert done and done[-1]["status"] == "error"


def test_build_phase_agent_instrument_flag(tmp_path):
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from shlepa_agent.phases import get_phase
    from shlepa_agent.runner import build_phase_agent

    cfg = load_config()
    model = TrackedModel(
        "stub-model", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )
    phase = get_phase("explore")
    instrumented = build_phase_agent(model, cfg, phase, instrument=True)
    plain = build_phase_agent(model, cfg, phase, instrument=False)
    assert instrumented.instrument is True
    assert not plain.instrument  # untouched default is None


def _v2_cfg(tmp_path, explore_requests: int, commit_requests: int):
    """Build a small test config (short budgets, tiny request caps)."""
    p = tmp_path / "cfg.toml"
    p.write_text(
        f"""
[agent]
temp = 0.2

[budget]
hard_time = 60.0
soft_time = 45.0
request_limit = {explore_requests}
token_budget = 100000
max_tokens = 1024
request_timeout = 30.0
request_wall = 60.0

[phases.explore]
tools = ["bash"]
requests = {explore_requests}
time = 45.0

[phases.commit]
tools = ["bash"]
requests = {commit_requests}
time = 30.0
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    return load_config(p)


def test_explore_done_finishes_without_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [{"final": FINAL_ANSWER}]
    output = _run(monkeypatch, stub_openai, tmp_path)
    assert output == FINAL_ANSWER
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert len(done) == 1
    assert done[0]["status"] == "done"
    assert not any(e.get("event") == "commit" for e in events)
    assert not any(e.get("event") == "budget" for e in events)
    assert not any(e.get("event") == "agent_error" for e in events)


class _LoopPhase:
    """A phase that always routes back to itself (infinite loop)."""

    id = "loop"
    terminal = False

    def tools(self, cfg):
        return ["bash"]

    def limits(self, cfg):
        from shlepa_agent.phases.base import PhaseLimits

        p = cfg.phases[self.id]
        return PhaseLimits(requests=p.requests, time=p.time)

    def history(self, state):
        return None

    def prompt(self, state):
        return "keep looping"

    def route(self, result, state):
        return self.id


def test_max_steps_guard_stops_looping_graph(
    monkeypatch, stub_openai, tmp_path, events
):
    stub_state["script"] = [{"final": FINAL_ANSWER}]
    p = tmp_path / "cfg.toml"
    p.write_text(
        """
[agent]
entry = "loop"
emergency = "commit"
max_steps = 3
temp = 0.2

[budget]
hard_time = 60.0
soft_time = 45.0
request_limit = 9
token_budget = 100000
max_tokens = 1024
request_timeout = 30.0
request_wall = 60.0

[phases.loop]
tools = ["bash"]
requests = 5
time = 45.0

[phases.commit]
tools = ["bash"]
requests = 5
time = 30.0
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config
    from shlepa_agent.phases import get_phase

    cfg = load_config(p)

    def factory(phase_id: str):
        if phase_id == "loop":
            return _LoopPhase()
        return get_phase(phase_id)

    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    asyncio.run(runner.run_prompt("t", agent_cfg=cfg, phase_factory=factory))
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert done[-1]["status"] == "budget"
    # Step guard tripped, emergency phase ran exactly once, then the run stopped.
    assert sum(1 for e in events if e.get("event") == "budget" and e.get("reason") == "max_steps") == 1
    assert sum(1 for e in events if e.get("event") == "commit" and e.get("start")) == 1
    # 3 loop runs + 1 emergency run: the loop did not continue past the guard.
    assert len(stub_state["bodies"]) == 4


def test_phase_error_retried_then_emergency(monkeypatch, stub_openai, tmp_path, events):
    # Unknown tool call -> UnexpectedModelBehavior: an unexpected phase ERROR
    # (not a budget breach). The stub is scripted to fail every request.
    stub_state["script"] = [
        {"tool_call": {"name": "no_such_tool", "arguments": {}}}
    ]
    from shlepa_agent.config import load_config

    cfg = load_config()  # packaged config: explore/commit max_retries = 2
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert done[-1]["status"] == "error"
    # Explore: initial attempt + exactly 2 retries.
    explore_retries = [
        e for e in events
        if e.get("event") == "phase_retry" and e.get("phase") == "explore"
    ]
    assert [e["attempt"] for e in explore_retries] == [2, 3]
    # Emergency phase ran (once), then the run finished.
    assert sum(1 for e in events if e.get("event") == "commit" and e.get("start")) == 1
    assert any(
        e.get("event") == "commit" and e.get("done") and "error" in e for e in events
    )


def test_log_contract_events_and_fields(monkeypatch, stub_openai, tmp_path, events):
    # One tool round-trip, then the final answer: exercises every regular
    # event the CLI (and trace tooling) may parse.
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo hi"}}},
        {"final": FINAL_ANSWER},
    ]
    _run(monkeypatch, stub_openai, tmp_path, task="make the file")
    by_event: dict[str, list[dict]] = {}
    for e in events:
        by_event.setdefault(e.get("event", ""), []).append(e)

    start = by_event.get("agent_start", [{}])
    for field in (
        "model", "base_url", "workdir", "prompt", "temp",
        "soft_time", "hard_time", "request_limit", "token_budget",
    ):
        assert field in start[0], f"agent_start missing {field}"
    assert start[0]["prompt"] == "make the file"

    usage = by_event.get("usage", [])
    assert usage, "no usage events"
    for field in (
        "request", "input_tokens", "output_tokens",
        "cumulative_input", "cumulative_output", "cumulative_total", "elapsed_s",
    ):
        assert field in usage[0], f"usage missing {field}"

    calls = by_event.get("llm_tool_call", [])
    results = by_event.get("llm_tool_result", [])
    assert calls and calls[0]["tool"] == "bash"
    assert results and results[0]["tool"] == "bash" and "result" in results[0]

    run_usage = by_event.get("run_usage", [])
    assert run_usage, "no run_usage events"
    for field in ("input_tokens", "output_tokens", "requests", "tool_calls"):
        assert field in run_usage[0], f"run_usage missing {field}"

    done = [e for e in by_event.get("agent_done", []) if "status" in e]
    assert done and done[-1]["status"] == "done"
    for field in ("status", "elapsed_s", "output"):
        assert field in done[-1], f"agent_done missing {field}"


def test_commit_event_fields(monkeypatch, stub_openai, tmp_path, events):
    # Budget breach in explore (1 request capped by a tool call) -> the
    # emergency commit run then succeeds: both commit events carry fields.
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo x"}}},
        {"final": FINAL_ANSWER},
    ]
    p = tmp_path / "cfg.toml"
    p.write_text(
        """
[agent]
temp = 0.2

[budget]
hard_time = 60.0
soft_time = 45.0
request_limit = 9
token_budget = 100000
max_tokens = 1024
request_timeout = 30.0
request_wall = 60.0

[phases.explore]
tools = ["bash"]
requests = 1
time = 45.0

[phases.commit]
tools = ["bash"]
requests = 9
time = 30.0
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    cfg = load_config(p)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    commits = [e for e in events if e.get("event") == "commit"]
    starts = [e for e in commits if e.get("start")]
    dones = [e for e in commits if e.get("done")]
    assert starts and dones
    for field in ("history_messages", "time_cap_s", "elapsed_s"):
        assert field in starts[0], f"commit start missing {field}"
    for field in ("done", "elapsed_s"):
        assert field in dones[0], f"commit done missing {field}"


def test_budget_error_is_not_retried(monkeypatch, stub_openai, tmp_path, events):
    # Persistent HTTP 500 -> TrackedModel retries once internally, then raises
    # ModelAPIError (a persistent model error = budget-class, never retried
    # by the runner). Both phases fail; no phase_retry events may appear.
    stub_state["script"] = [{"error": 500}]
    p = tmp_path / "cfg.toml"
    p.write_text(
        """
[agent]
temp = 0.2

[budget]
hard_time = 60.0
soft_time = 45.0
request_limit = 9
token_budget = 100000
max_tokens = 1024
request_timeout = 30.0
request_wall = 60.0

[phases.explore]
tools = ["bash"]
requests = 9
time = 45.0

[phases.commit]
tools = ["bash"]
requests = 9
time = 30.0
reasoning_effort = "low"
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    cfg = load_config(p)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert done[-1]["status"] == "budget"
    assert not any(e.get("event") == "phase_retry" for e in events)
    assert sum(1 for e in events if e.get("event") == "commit" and e.get("start")) == 1


def test_budget_breach_routes_to_commit_exactly_once(
    monkeypatch, stub_openai, tmp_path, events
):
    # Stub keeps issuing a bash tool call: the run loops until the per-phase
    # request cap trips UsageLimitExceeded (a budget breach).
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo x"}}}
    ]
    cfg = _v2_cfg(tmp_path, explore_requests=2, commit_requests=1)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    assert done[-1]["status"] == "budget"
    # Budget breach is a normal hand-off: commit runs exactly once, no retry.
    assert sum(1 for e in events if e.get("event") == "commit" and e.get("start")) == 1
    assert not any(e.get("event") == "phase_retry" for e in events)
    assert not any(e.get("event") == "agent_error" for e in events)
    assert any(e.get("event") == "budget" and e.get("reason") == "usage_or_time" for e in events)
    # explore: 2 capped requests, commit: 1 capped request
    assert len(stub_state["bodies"]) == 3
