"""t6: runner tests — v5 pipeline, handoffs, final_ask, retries.

The runner (shlepa_agent.runner) walks the plan -> work -> review cycle
(no task time limit T, no cycle cap): per-phase fixed time caps, the
one-shot toolless final_ask after a phase time-out, per-phase error
retries, and a stable log contract for the CLI.
"""

import asyncio
import json
import logging

import pytest

from stub_server import stub_state


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


def _run(
    monkeypatch, stub_openai, tmp_path, agent_cfg=None, task="create hello.txt", phase_factory=None
):
    from shlepa_agent import runner

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(
        runner.run_prompt(task, agent_cfg=agent_cfg, phase_factory=phase_factory)
    )


def _cfg(tmp_path, plan_time=60.0, work_time=180.0, commit_time=45.0, max_steps=8):
    """Small test config for the v5 pipeline (short phase caps)."""
    p = tmp_path / "cfg.toml"
    p.write_text(
        f"""
[agent]
temp = 0.6
send_temp = true
entry = "plan"
emergency = "emergency"
max_steps = {max_steps}

[budget]
max_tokens = 16384
request_timeout = 30.0

[tools.bash]
enabled = true
[tools.read]
enabled = true
[tools.write]
enabled = true
[tools.edit]
enabled = true

[phases.plan]
tools = ["read", "write", "edit", "bash"]
requests = 25
time = {plan_time}
soft_time = 45.0
soft_tokens = 15000
max_retries = 1

[phases.work]
tools = ["read", "write", "edit", "bash"]
requests = 100
time = {work_time}
soft_time = 105.0
max_retries = 1

[phases.commit]
tools = ["read", "write", "edit", "bash"]
requests = 20
time = {commit_time}
reasoning_effort = "low"
max_retries = 0

[phases.emergency]
tools = ["read", "write", "edit", "bash"]
requests = 20
reasoning_effort = "low"
max_retries = 0

[template]
blocks = ["system", "tools", "task", "extra", "previous_results",
          "phase_prompt", "output_schema", "note"]
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    return load_config(p)


def _plan_step(decision="work"):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "goal": "write /app/hello.txt with the content hello",
                "findings": "n/a",
                "steps": ["write the file", "verify it"],
                "decision": decision,
            },
        }
    }


def _work_step():
    # v5: WorkResult has no decision — the work phase always hands off to
    # the review phase.
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote hello.txt and verified it",
                "findings": "",
                "deliverable": "/app/hello.txt",
                "confidence": 1.0,
            },
        }
    }


def _review_step(status="ok", verdict="done"):
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "status": status,
                "verdict": verdict,
                "artifact": "/app/hello.txt",
                "checks": ["re-read the file -> content matches"],
                "hints": [] if verdict == "done" else ["re-examine the target"],
                "notes": "wrote hello.txt",
            },
        }
    }


def _phase_starts(events, phase):
    return [
        e for e in events if e.get("event") == "phase" and e.get("id") == phase and e.get("start")
    ]


def _status(events):
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    return done[-1]["status"] if done else None


# -- env / construction ---------------------------------------------------
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
    assert _status(events) == "error"


def test_build_phase_agent_instrument_flag_and_output_type(tmp_path):
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from shlepa_agent.outputs import PlanResult, ReviewResult
    from shlepa_agent.phases import get_phase
    from shlepa_agent.runner import build_phase_agent

    cfg = load_config()
    model = TrackedModel(
        "stub-model", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )
    plan = get_phase("plan")
    instrumented = build_phase_agent(model, cfg, plan, "some task", instrument=True)
    plain = build_phase_agent(model, cfg, plan, "some task", instrument=False)
    assert instrumented.instrument is True
    assert not plain.instrument  # untouched default is None
    # plan and commit are typed-output phases
    assert plan.output_type is PlanResult
    assert get_phase("commit").output_type is ReviewResult
    # Agents are named after their phase so the instrumentation's
    # invoke_agent spans are per-phase (agent_name=<phase-id>).
    assert instrumented.name == "plan"


def test_build_phase_agent_named_per_phase(tmp_path):
    """Each phase's agent carries the phase id as its name, so agent-run
    spans are 'invoke_agent <phase-id>' instead of indistinguishable
    'invoke_agent agent' spans. Issue #72."""
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from shlepa_agent.phases import get_phase
    from shlepa_agent.runner import build_phase_agent

    cfg = load_config()
    model = TrackedModel(
        "stub-model", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )
    for phase_id in ("plan", "work", "commit"):
        agent = build_phase_agent(model, cfg, get_phase(phase_id), "some task")
        assert agent.name == phase_id


def test_review_agent_is_read_only_from_packaged_config(tmp_path):
    """The baseline review (commit) phase builds with READ-ONLY tools only:
    it judges the transcript and re-checks the disk, but cannot
    read/write/run anything (no bash, no write/edit). The plan phase
    builds without bash/writes; the work phase is the only one with bash.
    """
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from shlepa_agent.phases import get_phase
    from shlepa_agent.runner import build_phase_agent

    cfg = load_config()  # the packaged baseline (no AGENT_TOOLSET in tests)
    model = TrackedModel(
        "stub-model", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )

    def names(phase_id: str) -> set[str]:
        agent = build_phase_agent(model, cfg, get_phase(phase_id), "some task")
        return set(agent._function_toolset.tools)

    assert names("commit") == {"read", "code_search", "file_outline"}
    # read-only review: read + search, no bash, no writes
    assert names("plan") == {"read", "recon", "code_search", "file_outline"}
    assert names("work") == {
        "read",
        "write",
        "edit",
        "bash",
        "recon",
        "code_search",
        "file_outline",
    }


# -- pipeline graph ---------------------------------------------------------
def test_pipeline_plan_work_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        _plan_step("work"),
        _work_step(),
        _review_step(),
    ]
    output = _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert output == "wrote hello.txt"  # ReviewResult.notes
    assert _status(events) == "done"
    starts = [(e["id"], e["cycle"]) for e in events if e.get("event") == "phase" and e.get("start")]
    assert [i for i, _ in starts] == ["plan", "work", "commit"]
    assert all(c == 0 for _, c in starts)  # no replan cycle
    assert len(stub_state["bodies"]) == 3  # one request per phase
    # phase_done events carry the phase statuses
    dones = [e for e in events if e.get("event") == "phase_done"]
    assert [e["status"] for e in dones] == ["done", "done", "done"]


def test_plan_commit_decision_is_ignored_always_works(monkeypatch, stub_openai, tmp_path, events):
    # The old trivial plan->commit shortcut is gone: the plan has no write
    # tools and can never deliver anything, so a hallucinated
    # decision="commit" is ignored and work still runs.
    stub_state["script"] = [_plan_step("commit"), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"
    assert _phase_starts(events, "work")  # work was NOT skipped
    assert _phase_starts(events, "commit")
    starts = [(e["id"], e["cycle"]) for e in events if e.get("event") == "phase" and e.get("start")]
    assert [i for i, _ in starts] == ["plan", "work", "commit"]
    assert len(stub_state["bodies"]) == 3


def test_review_next_round_starts_new_cycle(monkeypatch, stub_openai, tmp_path, events):
    # v5: no cycle cap — a "next_round" verdict starts a new plan/work
    # cycle while a full cycle (plan + work + review) fits the time left.
    stub_state["script"] = [
        _plan_step("work"),          # plan, cycle 0
        _work_step(),
        _review_step(verdict="next_round"),
        _plan_step("work"),          # plan, cycle 1 (review asked for it)
        _work_step(),
        _review_step(),              # done
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"
    plan_starts = _phase_starts(events, "plan")
    assert [e["cycle"] for e in plan_starts] == [0, 1]
    assert any(
        e.get("event") == "cycle" and e.get("reason") == "next_round" for e in events
    )
    assert len(stub_state["bodies"]) == 6


# -- final_ask handoff on phase hard timeout ---------------------------------
def test_commit_api_failure_reports_timeout(
    monkeypatch, stub_openai, tmp_path, events
):
    # A review that dies on a persistent model error (HTTP 500) is a normal
    # hand-off: the run must end as "timeout", not "done".
    stub_state["script"] = [
        _plan_step("work"),
        _work_step(),
        {"error": 500},
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "timeout"


def test_commit_invalid_verdict_reports_error(
    monkeypatch, stub_openai, tmp_path, events
):
    # A review that exhausts output retries with an invalid verdict is an
    # unexpected error: the run must end as "error", not "done".
    bad_review = _review_step()
    bad_review["tool_call"]["arguments"]["verdict"] = "explode"
    stub_state["script"] = [
        _plan_step("work"),
        _work_step(),
        bad_review,  # clamped by the stub: every retry sees the same bad step
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "error"


def test_commit_time_cap_reports_timeout(
    monkeypatch, stub_openai, tmp_path, events
):
    # A review cut by its own time cap must end the run as "timeout",
    # not "done" (the previous work phase had succeeded).
    stub_state["script"] = [
        _plan_step("work"),
        _work_step(),
        {"delay": 2.5, "tool_call": _review_step()["tool_call"]},
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path, commit_time=1.0))
    assert _status(events) == "timeout"


def test_plan_time_cap_triggers_final_ask_then_review(
    monkeypatch, stub_openai, tmp_path, events
):
    stub_state["script"] = [
        {"delay": 2.5, "final": "too slow — plan timed out"},
        {"final": "FINAL-ASK: wrote hello.txt"},
        _review_step(),  # v5: a plan breach hands off straight to the review
    ]
    cfg = _cfg(tmp_path, plan_time=1.0, work_time=30.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "timeout"  # plan was cut by its cap
    # the test config has send_temp on: every request (incl. final_ask) sends it
    assert all(b.get("temperature") == 0.6 for b in stub_state["bodies"])
    # plan was cut by its hard cap (budget), NOT retried
    assert any(
        e.get("event") == "budget" and "plan time cap" in (e.get("reason") or "") for e in events
    )
    assert not [e for e in events if e.get("event") == "phase_retry" and e.get("phase") == "plan"]
    # one toolless final_ask on the plan conversation, then the terminal review
    asks = [e for e in events if e.get("event") == "final_ask" and e.get("phase") == "plan"]
    assert asks[0].get("start") is True
    assert asks[-1].get("ok") is True
    assert not _phase_starts(events, "work")
    assert _phase_starts(events, "commit")
    assert len(stub_state["bodies"]) == 3
    # KV-cache reuse: the final_ask request prefix is byte-identical to the
    # plan phase's last request (same system message, same history prefix).
    bodies = stub_state["bodies"]
    fa = next(
        b
        for b in bodies
        if any("HARD TIME LIMIT REACHED" in str(m.get("content") or "") for m in b["messages"])
    )
    plan = bodies[0]
    assert fa["messages"][0] == plan["messages"][0]  # system: byte-identical
    assert fa["messages"][:-1] == plan["messages"][:-1]  # history prefix


def test_work_time_cap_triggers_final_ask_then_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        _plan_step("work"),
        {"delay": 2.5, "final": "too slow — work timed out"},
        {"final": "FINAL-ASK: wrote hello.txt"},
        _review_step(),
    ]
    cfg = _cfg(tmp_path, work_time=1.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "timeout"  # work was cut by its cap
    asks = [e for e in events if e.get("event") == "final_ask" and e.get("phase") == "work"]
    assert asks and asks[-1].get("ok") is True
    assert len(_phase_starts(events, "work")) == 1  # work was NOT rerun
    assert _phase_starts(events, "commit")
    assert len(stub_state["bodies"]) == 4


def test_step_guard_exhaustion_stops_run(monkeypatch, stub_openai, tmp_path, events):
    # max_steps=1 (dev knob): the plan phase runs, then the guard stops the
    # walk at the work boundary — with "timeout", no emergency routing.
    cfg = _cfg(tmp_path, max_steps=1)
    stub_state["script"] = [_plan_step("work")]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "timeout"
    assert any(
        e.get("event") == "budget" and e.get("reason") == "max_steps" for e in events
    )
    assert not _phase_starts(events, "work")
    assert not _phase_starts(events, "commit")
    assert not _phase_starts(events, "emergency")
    assert len(stub_state["bodies"]) == 1


# -- retries -----------------------------------------------------------------
def test_plan_error_retried_once_then_work(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.phases import PlanPhase, get_phase

    calls = {"n": 0}

    class _FlakyPlan(PlanPhase):
        def prompt(self, state):
            calls["n"] += 1
            if calls["n"] <= 1:
                raise RuntimeError("simulated plan failure")
            return super().prompt(state)

    def factory(phase_id):
        return _FlakyPlan() if phase_id == "plan" else get_phase(phase_id)

    stub_state["script"] = [
        _plan_step("work"),  # attempt 2 (attempt 1 dies before the request)
        _work_step(),
        _review_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path), phase_factory=factory)
    assert _status(events) == "done"
    retries = [e for e in events if e.get("event") == "phase_retry" and e.get("phase") == "plan"]
    assert [e["attempt"] for e in retries] == [2]
    # one phase entry; the retry is tracked by phase_retry, not a new phase start
    assert len(_phase_starts(events, "plan")) == 1
    assert len(stub_state["bodies"]) == 3  # no model request on the failed attempt


# -- temperature opt-in -----------------------------------------------------
def test_temperature_not_sent_by_default(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.delenv("SHLEPA_SEND_TEMP", raising=False)
    monkeypatch.delenv("SHLEPA_TEMP", raising=False)
    stub_state["script"] = [_plan_step("commit"), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all("temperature" not in b for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert "temp" not in start


def test_temperature_sent_when_send_temp_enabled(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    stub_state["script"] = [_plan_step("commit"), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.6 for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert start.get("temp") == 0.6


def test_temperature_env_value_override(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    monkeypatch.setenv("SHLEPA_TEMP", "0.9")
    stub_state["script"] = [_plan_step("commit"), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.9 for b in stub_state["bodies"])


# -- log contract ---------------------------------------------------------------
def test_log_contract_stable_events_and_fields(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo hi"}}},
        _plan_step("work"),
        _work_step(),
        _review_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    names = {e.get("event") for e in events}
    # CLI-parsed events keep their names
    assert {"usage", "agent_start", "agent_done", "agent_error"} & names == {
        "usage",
        "agent_start",
        "agent_done",
    }
    start = next(e for e in events if e.get("event") == "agent_start")
    for field in (
        "model",
        "base_url",
        "workdir",
        "prompt",
        "temp",
        "entry",
    ):
        assert field in start, f"agent_start lost stable field {field}"
    # v5 fixed-regime details are additive (unknown to the CLI, but logged);
    # there is NO t / t_source / hard_time / soft_time / commit_deadline
    assert {"plan_cap", "work_cap", "review_cap", "bash_cap", "llm_wall"} <= set(start)
    assert start["plan_cap"] == pytest.approx(80.0)
    assert start["work_cap"] == pytest.approx(120.0)
    assert start["review_cap"] == pytest.approx(60.0)
    assert start["bash_cap"] == pytest.approx(30.0)
    assert start["llm_wall"] == pytest.approx(180.0)
    usage = next(e for e in events if e.get("event") == "usage")
    for field in (
        "request", "input_tokens", "output_tokens", "cumulative_input", "cumulative_output"
    ):
        assert field in usage
    # v5 pipeline events
    assert {"phase", "phase_done"} <= names
    assert "llm_tool_call" in names  # the bash round-trip in the plan phase
    done = next(e for e in events if e.get("event") == "agent_done" and "status" in e)
    assert done["status"] in ("done", "timeout", "error")
    assert "elapsed_s" in done and "output" in done


# -- per-phase usage tagging (issue #73) -------------------------------------


class _StubStreamACM:
    """Async context manager mimicking ``agent.run_stream_events(...)``."""

    def __init__(self, events, on_enter):
        self._events = list(events)
        self._on_enter = on_enter

    async def __aenter__(self):
        self._on_enter()

        async def _gen():
            for ev in self._events:
                yield ev

        return _gen()

    async def __aexit__(self, *exc):
        return False


class _StubAgent:
    name = "stub"

    def __init__(self, on_enter, events=()):
        self._on_enter = on_enter
        self._events = events

    def run_stream_events(self, prompt, **kwargs):
        return _StubStreamACM(self._events, self._on_enter)


class _StubPhase:
    """Free-text phase with a fixed cap (no output_type, not terminal)."""

    output_type = None
    terminal = False

    def __init__(self, phase_id):
        self.id = phase_id

    def limits(self, cfg):
        from shlepa_agent.phases.base import PhaseLimits

        return PhaseLimits(requests=10, time=30.0)

    def history(self, state):
        return None

    def prompt(self, state):
        return "stub prompt"


def test_run_phase_sets_and_rotates_current_phase(tmp_path):
    """_run_phase sets the current phase on the shared model *before* the
    agent runs (so the phase's usage events carry it) and rotates it
    between phase runs (plan -> work). Issue #73."""
    from pathlib import Path

    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.config import load_config
    from shlepa_agent.model import TrackedModel
    from shlepa_agent.phases.base import RunState
    from shlepa_agent.runner import _run_phase
    from shlepa_agent.tools.base import AgentDeps

    cfg = load_config()
    model = TrackedModel(
        "stub-model",
        OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"),
        cfg,
    )
    state = RunState(
        task="stub task",
        deps=AgentDeps(workdir=Path(tmp_path), cfg=cfg, clock=model.elapsed),
        model=model,
    )
    assert model.current_phase is None

    seen: list = []
    for phase_id in ("plan", "work"):
        agent = _StubAgent(lambda: seen.append(model.current_phase))
        result = asyncio.run(_run_phase(state, _StubPhase(phase_id), agent))
        assert result.status == "done"
    # The phase was set BEFORE each agent run, and rotated across phases.
    assert seen == ["plan", "work"]
    assert model.current_phase == "work"
