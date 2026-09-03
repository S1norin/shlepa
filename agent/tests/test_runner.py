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


def _plan_step():
    # v6: PlanResult carries no `decision` field (w1-7) — every plan flows
    # to WORK; the former work|commit argument was removed.
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


def _handoff_step():
    # The typed partial_handoff final_ask answer (plan-timeout hand-off, v6).
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


# -- pipeline graph ---------------------------------------------------------
def test_pipeline_plan_work_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        _plan_step(),
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


def test_plan_phase_cannot_call_bash(monkeypatch, stub_openai, tmp_path, events):
    # v6: the plan toolset is read-only (read, recon, search). A model that
    # still asks for bash is refused by the tool surface (unknown tool),
    # nothing is executed, and the run carries on to work.
    from shlepa_agent.config import load_config

    # This test is about the plan tool surface, not the v6 salvage gate
    # (covered in test_salvage.py): keep the v5-shaped sequence.
    monkeypatch.setenv("SHLEPA_SALVAGE", "0")
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "touch hello.txt"}}},
        _plan_step(),
        _work_step(),
        _review_step(),
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert _status(events) == "done"
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "commit"]
    # the bash call was refused, never executed
    refused = [
        e for e in events
        if e.get("event") == "llm_tool_result" and e.get("tool") == "bash"
    ]
    assert refused, "expected a refusal for the out-of-surface bash call"
    assert "Unknown tool" in refused[0]["result"]
    assert not (tmp_path / "hello.txt").exists()


def test_trivial_plan_still_flows_through_work(monkeypatch, stub_openai, tmp_path, events):
    # v6 routing invariant: the plan -> commit shortcut is gone — even a
    # trivial plan (answer already known in PLAN) flows PLAN -> WORK ->
    # REVIEW; the work phase is what writes the file.
    stub_state["script"] = [_plan_step(), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == ["plan", "work", "commit"]
    assert len(stub_state["bodies"]) == 3


def test_review_next_round_starts_new_cycle(monkeypatch, stub_openai, tmp_path, events):
    # v5: no cycle cap — a "next_round" verdict starts a new plan/work
    # cycle while a full cycle (plan + work + review) fits the time left.
    stub_state["script"] = [
        _plan_step(),                # plan, cycle 0
        _work_step(),
        _review_step(verdict="next_round"),
        _plan_step(),                # plan, cycle 1 (review asked for it)
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
        _plan_step(),
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
        _plan_step(),
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
        _plan_step(),
        _work_step(),
        {"delay": 2.5, "tool_call": _review_step()["tool_call"]},
    ]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path, commit_time=1.0))
    assert _status(events) == "timeout"


def test_plan_time_cap_handoff_to_work(monkeypatch, stub_openai, tmp_path, events):
    # v6: a plan cut by its cap gets ONE toolless final_ask (typed
    # partial_handoff), then routes to WORK (a fresh run) — the review is
    # reached only through a completed work phase.
    stub_state["script"] = [
        {"delay": 2.5, "final": "too slow — plan timed out"},
        _handoff_step(),
        _work_step(),
        _review_step(),
    ]
    cfg = _cfg(tmp_path, plan_time=1.0, work_time=30.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "done"  # plan was cut, but work + review finished
    # the test config has send_temp on: every request (incl. final_ask) sends it
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
    assert starts == ["plan", "work", "commit"]
    assert len(stub_state["bodies"]) == 4
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
        if any(
            "TIME LIMIT REACHED" in str(m.get("content") or "") for m in b["messages"]
        )
    )
    plan = bodies[0]
    assert fa["messages"][0] == plan["messages"][0]  # system: byte-identical
    assert fa["messages"][:-1] == plan["messages"][:-1]  # history prefix


def test_plan_time_cap_v5_routing_under_knobs(monkeypatch, stub_openai, tmp_path, events):
    # A0 baseline arm: SHLEPA_ROUTE_PLAN_TIMEOUT=commit + SHLEPA_HANDOFF=off
    # reproduce the v5 routes — the v5 final_ask message, no hand-off block,
    # and the review straight after (work never starts).
    monkeypatch.setenv("SHLEPA_ROUTE_PLAN_TIMEOUT", "commit")
    monkeypatch.setenv("SHLEPA_HANDOFF", "off")
    stub_state["script"] = [
        {"delay": 2.5, "final": "too slow — plan timed out"},
        {"final": "FINAL-ASK: wrote hello.txt"},
        _review_step(),
    ]
    cfg = _cfg(tmp_path, plan_time=1.0)
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    assert _status(events) == "timeout"  # v5: a plan breach ends "timeout"
    asks = [e for e in events if e.get("event") == "final_ask" and e.get("phase") == "plan"]
    assert asks and asks[0].get("mode") == "off"
    assert not _phase_starts(events, "work")
    assert _phase_starts(events, "commit")
    assert len(stub_state["bodies"]) == 3


def test_plan_error_routes_to_work(monkeypatch, stub_openai, tmp_path, events):
    # v6: a plan that fails after its retries still reaches WORK, with a
    # direct-execution note (there is no plan to follow). Each failed plan
    # attempt consumes two stub steps (initial output call + one output
    # retry), so the script carries two bad steps per attempt.
    stub_state["script"] = [*(_bad_plan() for _ in range(4)), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=_cfg(tmp_path))
    assert _status(events) == "done"  # work + review finished the task
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    # the plan retry happens inside the plan phase (one start event)
    assert starts == ["plan", "work", "commit"]
    assert any(
        e.get("event") == "phase_retry" and e.get("phase") == "plan" for e in events
    )
    work_text = json.dumps(stub_state["bodies"][4])
    assert "the plan phase failed" in work_text
    assert "execute the task directly" in work_text


# -- v6 routing invariant: table-driven coverage of all plan/work outcomes ---
V6_ROUTING_CASES = [
    {
        "name": "plan_done_work",
        "script": [_plan_step(), _work_step(), _review_step()],
        "cfg": {},
        "phases": ["plan", "work", "commit"],
        "status": "done",
    },
    {
        "name": "plan_timeout_handoff_to_work",
        "script": [
            {"delay": 2.5, "final": "slow plan"},
            _handoff_step(),
            _work_step(),
            _review_step(),
        ],
        "cfg": {"plan_time": 1.0},
        "phases": ["plan", "work", "commit"],
        "status": "done",
    },
    {
        "name": "plan_error_direct_execution",
        # 2 failed plan attempts x 2 output calls each, then work + review.
        "script": [*(_bad_plan() for _ in range(4)), _work_step(), _review_step()],
        "cfg": {},
        # the plan retry happens inside the plan phase (one start event)
        "phases": ["plan", "work", "commit"],
        "status": "done",
    },
    {
        "name": "work_timeout_final_ask_review",
        "script": [
            _plan_step(),
            {"delay": 2.5, "final": "slow work"},
            {"final": "FINAL-ASK: wrote hello.txt"},
            _review_step(),
        ],
        "cfg": {"work_time": 1.0},
        "phases": ["plan", "work", "commit"],
        "status": "timeout",
    },
    {
        "name": "work_error_review",
        # 2 failed work attempts x 2 output calls each, then the review.
        "script": [
            _plan_step(),
            *(_bad_work() for _ in range(4)),
            _review_step(),
        ],
        "cfg": {},
        # the work retry happens inside the work phase (one start event)
        "phases": ["plan", "work", "commit"],
        "status": "error",
    },
]


@pytest.mark.parametrize(
    "case", V6_ROUTING_CASES, ids=[case["name"] for case in V6_ROUTING_CASES]
)
def test_v6_routing_table(monkeypatch, stub_openai, tmp_path, events, case):
    # The v6 default knobs route every plan outcome to WORK and keep the
    # v5 work-timeout/error routes to the review.
    stub_state["script"] = case["script"]
    cfg = _cfg(tmp_path, **case["cfg"])
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=cfg)
    starts = [e["id"] for e in events if e.get("event") == "phase" and e.get("start")]
    assert starts == case["phases"], case["name"]
    assert _status(events) == case["status"], case["name"]


def test_work_time_cap_triggers_final_ask_then_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        _plan_step(),
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
    stub_state["script"] = [_plan_step()]
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
        _plan_step(),        # attempt 2 (attempt 1 dies before the request)
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
    stub_state["script"] = [_plan_step(), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all("temperature" not in b for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert "temp" not in start


def test_temperature_sent_when_send_temp_enabled(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    stub_state["script"] = [_plan_step(), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.6 for b in stub_state["bodies"])
    start = next(e for e in events if e.get("event") == "agent_start")
    assert start.get("temp") == 0.6


def test_temperature_env_value_override(monkeypatch, stub_openai, tmp_path, events):
    from shlepa_agent.config import load_config

    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    monkeypatch.setenv("SHLEPA_TEMP", "0.9")
    stub_state["script"] = [_plan_step(), _work_step(), _review_step()]
    _run(monkeypatch, stub_openai, tmp_path, agent_cfg=load_config())
    assert stub_state["bodies"]
    assert all(b.get("temperature") == 0.9 for b in stub_state["bodies"])


# -- log contract ---------------------------------------------------------------
def test_log_contract_stable_events_and_fields(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [
        {"tool_call": {"name": "bash", "arguments": {"command": "echo hi"}}},
        _plan_step(),
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
    assert start["plan_cap"] == pytest.approx(30.0)  # v6 regime
    assert start["work_cap"] == pytest.approx(120.0)
    assert start["review_cap"] == pytest.approx(45.0)
    assert start["bash_cap"] == pytest.approx(30.0)
    assert start["llm_wall"] == pytest.approx(180.0)
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
    # v5 pipeline events
    assert {"phase", "phase_done"} <= names
    assert "llm_tool_call" in names  # the bash round-trip in the plan phase
    done = next(e for e in events if e.get("event") == "agent_done" and "status" in e)
    assert done["status"] in ("done", "timeout", "error")
    assert "elapsed_s" in done and "output" in done
