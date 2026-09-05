"""v6-rewrite runner tests: the HARD cycle regime.

The runner (shlepa_agent.runner) executes exactly ``max_cycles``
(default 2) plan -> work cycles with a REVIEW relay (toolless
distillation, typed ReviewResult) between cycles:

    plan -> work -> review -> plan -> work -> exit

Per-phase fixed time caps, the one-shot toolless final_ask after a work
time-out, typed partial plan hand-off, per-phase error retries, relay
failures that never block the loop, and a stable log contract for the
CLI.
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


def _cfg(
    tmp_path,
    plan_time=60.0,
    work_time=180.0,
    review_time=45.0,
    max_steps=8,
    max_cycles=2,
):
    """Small test config for the hard-cycle pipeline (short phase caps)."""
    p = tmp_path / "cfg.toml"
    p.write_text(
        f"""
[agent]
temp = 0.6
send_temp = true
entry = "plan"
emergency = "emergency"
max_steps = {max_steps}
max_cycles = {max_cycles}

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

[phases.review]
requests = 20
time = {review_time}
reasoning_effort = "low"
max_retries = 0

[phases.commit]
tools = ["read", "write", "edit", "bash"]
requests = 20
time = 45.0
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


def _plan_step():
    # Every plan flows to WORK (no decision field); the work phase writes.
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "goal": "write /app/hello.txt with the content hello",
                "findings": "n/a",
                "steps": ["write the file", "verify it"],
            },
        }
    }


def _work_step():
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


def _handoff_step():
    # The typed partial_handoff final_ask answer (plan-timeout hand-off).
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "objective": "write /app/hello.txt with the content hello",
                "findings": ["task wants hello.txt (task statement)"],
                "files_seen": ["/app/task.txt"],
                "hypotheses": [],
                "failed_paths": [],
                "next_action": "write the file and verify it",
                "deliverable_path_if_known": "/app/hello.txt",
            },
        }
    }


def _bad_plan():
    step = _plan_step()
    step["tool_call"]["arguments"]["steps"] = "not-a-list"  # invalid PlanResult
    return step


def _bad_work():
    step = _work_step()
    step["tool_call"]["arguments"]["confidence"] = "high"  # invalid: float
    return step


def _relay_step(done=False, problems=None, hints=None):
    """One typed relay step (the new ReviewResult schema)."""
    return {
        "tool_call": {
            "name": "final_result",
            "arguments": {
                "summary": "wrote hello.txt",
                "done": done,
                "problems": problems if problems is not None else [],
                "hints_next": hints if hints is not None else [],
            },
        }
    }


def _bad_relay():
    step = _relay_step()
    step["tool_call"]["arguments"]["done"] = "explode"  # invalid: bool
    return step


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
    # plan and review are typed-output phases
    assert plan.output_type is PlanResult
    assert get_phase("review").output_type is ReviewResult


# -- pipeline graph ---------------------------------------------------------
def test_pipeline_hard_cycle_two_cycles(monkeypatch, stub_openai, tmp_path, events):
    # The shipped default: exactly two plan/work cycles, a relay between
    # them, no relay after the last cycle, and no commit phase at all.
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    output = _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert output == "wrote hello.txt and verified it"  # the last work summary
    assert _status(events) == "done"
    starts = [(e["id"], e["cycle"]) for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == [
        ("plan", 0),
        ("work", 0),
        ("review", 1),
        ("plan", 1),
        ("work", 1),
    ]
    assert len(stub_state["bodies"]) == 5  # one request per phase
    dones = [e for e in events if e.get("event") == "phase_done"]
    assert [e["status"] for e in dones] == ["done"] * 5
    # the relay runs between cycles only
    relays = [e for e in events if e.get("event") == "cycle" and e.get("reason") == "relay"]
    assert len(relays) == 1


def test_max_cycles_knob_one_cycle(monkeypatch, stub_openai, tmp_path, events):
    # max_cycles=1: no relay at all — the relay only exists between cycles.
    stub_state["script"] = [_plan_step(), _work_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path, max_cycles=1))
    assert _status(events) == "done"
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work"]
    assert not [e for e in events if e.get("event") == "cycle" and e.get("reason") == "relay"]
    assert len(stub_state["bodies"]) == 2


def test_relay_error_does_not_block_next_cycle(monkeypatch, stub_openai, tmp_path, events):
    # A relay that exhausts its output retries is an error for the relay
    # ONLY: the harness logs review_fallback and the next cycle starts.
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _bad_relay(),  # clamped: every relay attempt sees the same bad step
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "review", "plan", "work"]
    fb = [e for e in events if e.get("event") == "review_fallback"]
    assert fb and fb[0]["reason"] == "error"


def test_plan_phase_cannot_call_bash(monkeypatch, stub_openai, tmp_path, events):
    # The shipped plan tool surface is read-only (read, recon, search) via
    # the tool policy: a model that still asks for bash is refused by the
    # tool surface (unknown tool), nothing is executed, run continues.
    from shlepa_agent.config import load_config

    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "touch hello.txt"}}},
        _plan_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert _status(events) == "done"
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "review", "plan", "work"]
    refused = [
        e for e in events
        if e.get("event") == "llm_tool_result" and e.get("tool") == "bash"
    ]
    assert refused, "expected a refusal for the out-of-surface bash call"
    assert "Unknown tool" in refused[0]["result"]
    assert not (tmp_path / "hello.txt").exists()


def test_relay_fields_carried_into_cycle2(monkeypatch, stub_openai, tmp_path, events):
    # The relay's typed fields (summary/problems/hints_next) all reach the
    # cycle-2 PLAN and WORK prompts — not just the summary.
    stub_state["script"] = [
        _plan_step(),
        _work_step(),
        _relay_step(done=True, problems=["out.json is not valid json"], hints=["rewrite it"])
        ,
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"
    bodies = stub_state["bodies"]
    plan2 = json.dumps(bodies[3])
    work2 = json.dumps(bodies[4])
    for body in (plan2, work2):
        assert "out.json is not valid json" in body
        assert "rewrite it" in body
        assert "known problems" in body
        assert "do next (by value)" in body
        assert "complete and correct" in body  # done=True context note


# -- final_ask / handoff / caps ---------------------------------------------
def test_plan_time_cap_handoff_to_work(monkeypatch, stub_openai, tmp_path, events):
    # A plan cut by its cap gets ONE toolless final_ask (typed
    # partial_handoff), then WORK starts (a fresh run). The run still
    # completes its cycles; the plan cut does not change the final status.
    stub_state["script"] = [
        {"delay": 2.5, "final": "too slow — plan timed out"},
        _handoff_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    cfg = _cfg(tmp_path, plan_time=1.0, work_time=30.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "done"  # plan was cut, but work finished
    assert all(b.get("temperature") == 0.6 for b in stub_state["bodies"])
    # plan was cut by its hard cap (budget), NOT retried
    assert any(
        e.get("event") == "budget" and "plan time cap" in (e.get("reason") or "") for e in events
    )
    assert not [e for e in events if e.get("event") == "phase_retry" and e.get("phase") == "plan"]
    # one typed final_ask on the plan conversation, then the work phase
    asks = [e for e in events if e.get("event") == "final_ask" and e.get("phase") == "plan"]
    assert asks[0].get("start") is True
    assert asks[0].get("mode") == "partial"
    assert asks[-1].get("ok") is True
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "review", "plan", "work"]
    assert len(stub_state["bodies"]) == 6
    # WORK's user message carries the cut-off note + the hand-off JSON.
    work_text = json.dumps(stub_state["bodies"][2])
    assert "cut off by its time cap" in work_text
    assert "PARTIAL HANDOFF" in work_text
    assert "deliverable_path_if_known" in work_text
    # KV-cache reuse: the final_ask request prefix is byte-identical to the
    # plan phase's last request (same system message, same history prefix).
    bodies = stub_state["bodies"]
    fa = next(
        b
        for b in bodies
        if any("TIME LIMIT REACHED" in str(m.get("content") or "") for m in b["messages"])
    )
    plan = bodies[0]
    assert fa["messages"][0] == plan["messages"][0]  # system: byte-identical
    assert fa["messages"][:-1] == plan["messages"][:-1]  # history prefix


def test_plan_error_routes_to_work(monkeypatch, stub_openai, tmp_path, events):
    # A plan that fails after its retries still reaches WORK, with a
    # direct-execution note (there is no plan to follow). Each failed plan
    # attempt consumes two stub steps (initial output call + one output
    # retry), so the script carries two bad steps per attempt.
    stub_state["script"] = [*(_bad_plan() for _ in range(4)), _work_step(), _relay_step(), _plan_step(), _work_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"  # work finished the task
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    # the plan retry happens inside the plan phase (one start event)
    assert starts == ["plan", "work", "review", "plan", "work"]
    assert any(
        e.get("event") == "phase_retry" and e.get("phase") == "plan" for e in events
    )
    work_text = json.dumps(stub_state["bodies"][4])
    assert "the plan phase failed" in work_text
    assert "execute the task directly" in work_text


# -- routing table: every plan/work outcome under the hard-cycle regime ----
ROUTING_CASES = [
    {
        "name": "plan_done_work",
        "script": [_plan_step(), _work_step(), _relay_step(), _plan_step(), _work_step()],
        "cfg": {},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "done",
    },
    {
        "name": "plan_timeout_handoff_to_work",
        "script": [
            {"delay": 2.5, "final": "slow plan"},
            _handoff_step(),
            _work_step(),
            _relay_step(),
            _plan_step(),
            _work_step(),
        ],
        "cfg": {"plan_time": 1.0},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "done",
    },
    {
        "name": "plan_error_direct_execution",
        "script": [*(_bad_plan() for _ in range(4)), _work_step(), _relay_step(), _plan_step(), _work_step()],
        "cfg": {},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "done",
    },
    {
        "name": "work_timeout_final_ask_then_relay",
        # work cut in cycle 1 -> final_ask -> relay -> cycle 2 -> done.
        "script": [
            _plan_step(),
            {"delay": 2.5, "final": "slow work"},
            {"final": "FINAL-ASK: wrote hello.txt"},
            _relay_step(),
            _plan_step(),
            _work_step(),
        ],
        "cfg": {"work_time": 1.0},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "done",
    },
    {
        "name": "work_timeout_last_cycle_reports_timeout",
        # work cut in the LAST cycle -> final_ask -> run ends "timeout".
        "script": [
            _plan_step(),
            _work_step(),
            _relay_step(),
            _plan_step(),
            {"delay": 2.5, "final": "slow work"},
            {"final": "FINAL-ASK: wrote hello.txt"},
        ],
        "cfg": {"work_time": 1.0},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "timeout",
    },
    {
        "name": "work_error_last_cycle_reports_error",
        "script": [_plan_step(), _work_step(), _relay_step(), _plan_step(), *(_bad_work() for _ in range(2))],
        "cfg": {},
        "phases": ["plan", "work", "review", "plan", "work"],
        "status": "error",
    },
]


@pytest.mark.parametrize(
    "case", ROUTING_CASES, ids=[case["name"] for case in ROUTING_CASES]
)
def test_routing_table(monkeypatch, stub_openai, tmp_path, events, case):
    # The hard-cycle regime: every plan outcome reaches WORK, every work
    # timeout gets a final_ask, the relay only ever runs between cycles,
    # and the LAST work decides the final status.
    stub_state["script"] = case["script"]
    cfg = _cfg(tmp_path, **case["cfg"])
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == case["phases"], case["name"]
    assert _status(events) == case["status"], case["name"]


def test_work_time_cap_triggers_final_ask_then_relay(monkeypatch, stub_openai, tmp_path, events):
    # Cycle-1 work cut: final_ask (toolless) then the relay — the relay
    # does NOT judge, it distills; the next cycle still runs.
    stub_state["script"] = [
        _plan_step(),
        {"delay": 2.5, "final": "too slow — work timed out"},
        {"final": "FINAL-ASK: wrote hello.txt"},
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    cfg = _cfg(tmp_path, work_time=1.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "done"  # cycle-2 work finished
    asks = [e for e in events if e.get("event") == "final_ask" and e.get("phase") == "work"]
    assert asks and asks[-1].get("ok") is True
    assert len(_phase_starts(events, "work")) == 2  # the work phase reran (cycle 2)
    assert len(_phase_starts(events, "review")) == 1  # relay between the cycles
    assert len(stub_state["bodies"]) == 6


def test_step_guard_exhaustion_stops_run(monkeypatch, stub_openai, tmp_path, events):
    # max_steps=1 + max_cycles=3 (dev knobs): cycle 1 (plan+work) runs,
    # the relay starts, then the guard stops the walk BETWEEN cycles —
    # with "timeout" (it stops between cycles, never mid-last-cycle).
    cfg = _cfg(tmp_path, max_steps=1, max_cycles=3)
    stub_state["script"] = [_plan_step(), _work_step(), _relay_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "timeout"
    assert any(
        e.get("event") == "budget" and e.get("reason") == "max_steps" for e in events
    )
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "review"]  # cycle 2 never starts
    assert not _phase_starts(events, "commit")
    assert not _phase_starts(events, "emergency")
    assert len(stub_state["bodies"]) == 3


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
        _plan_step(),  # attempt 2 (attempt 1 dies before the request)
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path), phase_factory=factory)
    assert _status(events) == "done"
    retries = [e for e in events if e.get("event") == "phase_retry" and e.get("phase") == "plan"]
    assert [e["attempt"] for e in retries] == [2]
    # one start per cycle (2 cycles); the retry is phase_retry, not a new start
    assert len(_phase_starts(events, "plan")) == 2
    assert len(stub_state["bodies"]) == 5  # no model request on the failed attempt


# -- temperature opt-in -----------------------------------------------------
def test_temperature_not_sent_by_default(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.delenv("SHLEPA_SEND_TEMP", raising=False)
    monkeypatch.delenv("SHLEPA_TEMP", raising=False)
    stub_state["script"] = [_plan_step(), _work_step(), _relay_step(), _plan_step(), _work_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all("temperature" not in b for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert "temp" not in start


def test_temperature_sent_when_send_temp_enabled(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    stub_state["script"] = [_plan_step(), _work_step(), _relay_step(), _plan_step(), _work_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.6 for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert start.get("temp") == 0.6


def test_temperature_env_value_override(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    monkeypatch.setenv("SHLEPA_TEMP", "0.9")
    stub_state["script"] = [_plan_step(), _work_step(), _relay_step(), _plan_step(), _work_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.9 for b in stub_state["bodies"])


# -- log contract ---------------------------------------------------------------
def test_log_contract_stable_events_and_fields(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo hi"}}},
        _plan_step(),
        _work_step(),
        _relay_step(),
        _plan_step(),
        _work_step(),
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
    # fixed-regime details are additive; no t / hard_time / soft_time fields
    assert {"plan_cap", "work_cap", "review_cap", "bash_cap", "llm_wall"} <= set(start)
    assert start["plan_cap"] == pytest.approx(30.0)
    assert start["work_cap"] == pytest.approx(120.0)
    assert start["review_cap"] == pytest.approx(45.0)
    assert start["bash_cap"] == pytest.approx(30.0)
    assert start["llm_wall"] == pytest.approx(180.0)
    assert start["max_cycles"] == 2
    usage = next(e for e in events if e.get("event") == "usage")
    for field in (
        "request",
        "input_tokens",
        "output_tokens",
        "cache_read",
        "cache_write",
        "cumulative_input",
        "cumulative_output",
        "cumulative_cache_read",
        "cumulative_cache_write",
    ):
        assert field in usage
    # hard-cycle pipeline events
    assert {"phase", "phase_done", "cycle"} <= names
    assert "llm_tool_call" in names  # the bash round-trip in the plan phase
    done = next(e for e in events if e.get("event") == "agent_done" and "status" in e)
    assert done["status"] in ("done", "timeout", "error")
    assert "elapsed_s" in done and "output" in done


# -- caps: relay envelope -------------------------------------------------------
def test_review_subcaps_configured():
    # The legacy COMMIT/REPAIR/decide subcaps still describe the shipped
    # [phases.commit] (disabled, but kept on disk).
    from shlepa_agent import budget
    from shlepa_agent.config import load_config

    assert budget.REVIEW_CAP == 45.0
    assert (
        budget.REVIEW_SUBCAP_VERIFY
        + budget.REVIEW_SUBCAP_REPAIR
        + budget.REVIEW_SUBCAP_DECIDE
        == budget.REVIEW_CAP
    )
    cfg = load_config()  # production config
    assert cfg.phases["commit"].time == budget.REVIEW_SUBCAP_VERIFY
    assert cfg.phases["repair"].time == budget.REVIEW_SUBCAP_REPAIR


def test_review_subcaps_knob_restores_v5_envelope(monkeypatch):
    from shlepa_agent.config import load_config
    from shlepa_agent.phases.commit import CommitPhase

    cfg = load_config()
    phase = CommitPhase()
    assert phase.limits(cfg).time == 15.0  # VERIFY subcap
    monkeypatch.setenv("SHLEPA_REVIEW_SUBCAPS", "0")
    assert phase.limits(cfg).time is None  # regime: REVIEW_CAP 45 s


def test_relay_time_knob(monkeypatch):
    # The relay has its own regime cap (45 s) and a dev knob
    # SHLEPA_REVIEW_TIME that overrides [phases.review].time.
    from shlepa_agent.config import load_config
    from shlepa_agent.phases.review import ReviewPhase

    cfg = load_config()
    phase = ReviewPhase()
    assert phase.limits(cfg).time is None  # regime: REVIEW_CAP 45 s
    monkeypatch.setenv("SHLEPA_REVIEW_TIME", "10")
    assert phase.limits(load_config()).time == 10.0
