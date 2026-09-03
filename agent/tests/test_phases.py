"""t5: phase protocol, the four pipeline phases, structured results.

Covers: PhaseResult JSON roundtrip, RunState.results/cycles, the phase
registry (plan/work/commit/emergency; explore is gone), config-driven
toolsets and limits (hard vs advisory soft), fresh vs continued history,
trimmed continuation history on synthetic message lists, and phase prompts
(phase instructions, advisory limits, output schema, previous results).
"""

import json
from pathlib import Path
from types import SimpleNamespace

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)

from shlepa_agent.config import load_config
from shlepa_agent.outputs import PlanResult, ReviewResult, WorkResult
from shlepa_agent.phases import (
    CommitPhase,
    EmergencyPhase,
    PhaseResult,
    PlanPhase,
    RunState,
    WorkPhase,
    get_phase,
    trim_history,
)
from shlepa_agent.tools import AgentDeps


def _state(task="Create hello.txt with the exact content hello", last_messages=None):
    cfg = load_config()
    deps = AgentDeps(
        workdir=Path("/tmp"),
        cfg=cfg,
        clock=lambda: 0.0,
    )
    model = SimpleNamespace(
        last_messages=last_messages if last_messages is not None else [],
        elapsed=lambda: 0.0,
    )
    return RunState(task=task, deps=deps, model=model)


# -- PhaseResult / RunState -------------------------------------------------
def test_phase_result_json_roundtrip():
    result = PhaseResult(
        status="done", summary="wrote hello.txt", deliverable="hello.txt", iteration=1
    )
    payload = result.model_dump_json()
    restored = PhaseResult.model_validate(json.loads(payload))
    assert restored == result
    assert PhaseResult().status == "done"


def test_phase_result_carries_typed_output():
    plan = PlanResult(goal="write /app/out.txt", steps=["echo hi"])
    result = PhaseResult(status="done", summary=plan.model_dump_json(), output=plan)
    assert result.output.goal == "write /app/out.txt"
    # output is Any-typed: the JSON roundtrip keeps the data (as a dict)
    restored = PhaseResult.model_validate(json.loads(result.model_dump_json()))
    assert restored.output["steps"] == ["echo hi"]


def test_plan_result_has_no_routing_decision():
    # v6: strictly linear pipeline — PlanResult carries no work|commit
    # decision, and the plan prompt has no decision instructions.
    assert "decision" not in PlanResult.model_fields
    from shlepa_agent.phases.plan import PlanPhase

    state = _state()
    prompt = PlanPhase().prompt(state)
    assert "decision" not in prompt
    assert '"commit"' not in prompt  # no commit-shortcut instructions


def test_run_state_holds_one_result_per_phase_and_cycles():
    state = _state()
    state.results["work"] = PhaseResult(status="timeout", summary="cut off")
    state.results["commit"] = PhaseResult(status="done")
    assert state.cfg is state.deps.cfg
    assert state.results["work"].status == "timeout"
    assert state.cycles == 0
    state.cycles += 1
    assert state.cycles == 1


# -- registry ------------------------------------------------------------------
def test_registry_resolves_all_four_phase_ids():
    cfg = load_config()
    # packaged config: empty entry = always start at the plan phase (v5)
    assert cfg.agent.entry == ""
    assert isinstance(get_phase("plan"), PlanPhase)
    assert isinstance(get_phase("work"), WorkPhase)
    assert isinstance(get_phase("commit"), CommitPhase)
    assert isinstance(get_phase(cfg.agent.emergency), EmergencyPhase)
    # explore was removed in the v3 pipeline
    phases = (PlanPhase(), WorkPhase(), CommitPhase(), EmergencyPhase())
    assert "explore" not in {p.id for p in phases}
    try:
        get_phase("nope")
        assert False, "expected KeyError"
    except KeyError as e:
        assert "nope" in str(e)


def test_terminal_flags():
    assert CommitPhase().terminal is True
    assert EmergencyPhase().terminal is True
    assert PlanPhase().terminal is False
    assert WorkPhase().terminal is False


def test_output_types():
    assert PlanPhase.output_type is PlanResult
    assert WorkPhase.output_type is WorkResult
    assert CommitPhase.output_type is ReviewResult
    assert EmergencyPhase.output_type is None


# -- continuation history trimming ---------------------------------------------
def test_trim_history_drops_trailing_prompt_without_tool_return():
    msgs = [
        ModelRequest(parts=[TextPart("hi")]),
        ModelResponse(parts=[TextPart("ok")]),
        ModelRequest(parts=[TextPart("retry")]),
    ]
    out = trim_history(msgs)
    assert out == msgs[:2]


def test_trim_history_keeps_trailing_tool_return_request():
    msgs = [
        ModelResponse(parts=[ToolCallPart("bash", {"command": "ls"}, tool_call_id="c1")]),
        ModelRequest(parts=[ToolReturnPart("bash", "out", tool_call_id="c1")]),
    ]
    assert trim_history(msgs) == msgs


def test_trim_history_drops_dangling_tool_call_response():
    msgs = [
        ModelRequest(parts=[TextPart("hi")]),
        ModelResponse(parts=[TextPart("ok")]),
        ModelResponse(parts=[ToolCallPart("bash", {"command": "ls"}, tool_call_id="c1")]),
    ]
    out = trim_history(msgs)
    assert out == msgs[:2]


def test_commit_and_emergency_continue_the_last_conversation():
    msgs = [
        ModelRequest(parts=[TextPart("hi")]),
        ModelResponse(parts=[TextPart("ok")]),
    ]
    state = _state(last_messages=msgs)
    assert CommitPhase().history(state) == msgs
    assert EmergencyPhase().history(state) == msgs


def test_plan_and_work_are_fresh_runs():
    state = _state(last_messages=[ModelRequest(parts=[TextPart("hi")])])
    assert PlanPhase().history(state) is None
    assert WorkPhase().history(state) is None


# -- config-driven toolsets and limits -----------------------------------------
def test_phase_toolsets_from_config():
    cfg = load_config()
    # v6: the plan phase is read-only (no bash/write/edit); work gains
    # recon + search (structured exploration).
    assert PlanPhase().tools(cfg) == ["read", "recon", "search"]
    assert WorkPhase().tools(cfg) == ["read", "write", "edit", "bash", "recon", "search"]
    for phase in (CommitPhase(), EmergencyPhase()):
        assert phase.tools(cfg) == ["read", "write", "edit", "bash"]


def test_phase_limits_from_config():
    cfg = load_config()
    plan = PlanPhase().limits(cfg)
    assert plan.requests == 25
    assert plan.time is None  # cap = regime constant (budget.py, 30s)
    assert plan.soft_time == 25.0  # advisory, under the 30s cap
    assert plan.soft_tokens == 15000
    assert plan.reasoning_effort is None

    work = WorkPhase().limits(cfg)
    assert work.requests == 100
    assert work.time is None  # cap = regime constant (budget.py)
    assert work.soft_time == 105.0  # advisory, under the 120s cap
    assert work.soft_tokens is None  # no token note for work

    commit = CommitPhase().limits(cfg)
    assert commit.requests == 20
    assert commit.time is None  # cap = regime constant (budget.py)
    assert commit.soft_time == 35.0  # advisory, under the 45s cap
    assert commit.soft_tokens == 20000
    assert commit.reasoning_effort == "low"

    emergency = EmergencyPhase().limits(cfg)
    assert emergency.requests == 20
    assert emergency.time is None
    assert emergency.reasoning_effort == "low"


def test_limits_note_rendered_regime_caps():
    state = _state()
    plan_note = PlanPhase().limits_note(state)
    # fixed regime caps (plan 30s in v6) + advisory soft values
    assert "hard-capped at 30s" in plan_note
    assert "25s" in plan_note
    assert "15000" in plan_note
    work_note = WorkPhase().limits_note(state)
    assert "hard-capped at 120s" in work_note
    assert "cycle 1" in work_note  # state.cycles == 0 -> "this is cycle 1"
    commit_note = CommitPhase().limits_note(state)
    # the review (commit) phase gets its fixed regime cap (45s)
    assert "hard-capped at 45s" in commit_note


def test_limits_note_time_override():
    # an explicit [phases.*].time override (dev knob) beats the regime cap
    cfg = load_config().model_copy(deep=True)
    cfg.phases["plan"].time = 12.0
    deps = AgentDeps(workdir=Path("/tmp"), cfg=cfg, clock=lambda: 0.0)
    model = SimpleNamespace(last_messages=[])
    state = RunState(task="t", deps=deps, model=model)
    note = PlanPhase().limits_note(state)
    assert "hard-capped at 12s" in note


def test_max_retries_from_config():
    cfg = load_config()
    assert cfg.phases["plan"].max_retries == 1
    assert cfg.phases["work"].max_retries == 1
    assert cfg.phases["commit"].max_retries == 0
    assert cfg.phases["emergency"].max_retries == 0


# -- prompts ---------------------------------------------------------------------
def test_plan_prompt_carries_instructions_schema_and_limits():
    state = _state()
    prompt = PlanPhase().prompt(state)
    assert "PHASE INSTRUCTIONS" in prompt
    assert "PLAN PHASE" in prompt
    assert "final_result" in prompt  # output schema block
    assert "30s" in prompt  # advisory limits (v6 plan cap)
    # the task text lives in the system message, not the user prompt
    assert "Create hello.txt with the exact content hello" not in prompt
    # fresh first pass: no previous results block (the plan instructions
    # mention the block name in prose — check header + content instead)
    assert "RESULTS OF PREVIOUS PHASES\nwork phase" not in prompt


def test_plan_prompt_on_replan_carries_previous_work_result():
    state = _state()
    work = WorkResult(summary="tried")
    state.results["work"] = PhaseResult(
        status="done", summary=work.model_dump_json(), output=work,
    )
    prompt = PlanPhase().prompt(state)
    assert "RESULTS OF PREVIOUS PHASES" in prompt
    assert "tried" in prompt


def test_plan_prompt_on_replan_carries_review_hints():
    state = _state()
    work = WorkResult(summary="tried")
    state.results["work"] = PhaseResult(
        status="done", summary=work.model_dump_json(), output=work,
    )
    review = ReviewResult(
        status="partial",
        verdict="next_round",
        artifact="/app/out.json",
        hints=["ip_addresses must be sorted descending", "add the port field"],
    )
    state.results["commit"] = PhaseResult(
        status="done", summary=review.model_dump_json(), output=review,
    )
    prompt = PlanPhase().prompt(state)
    assert "review phase verdict (previous cycle): next_round" in prompt
    assert "ip_addresses must be sorted descending" in prompt
    assert "add the port field" in prompt


def test_work_prompt_carries_plan_result():
    state = _state()
    plan = PlanResult(goal="write /app/out.txt", steps=["echo"])
    state.results["plan"] = PhaseResult(
        status="done", summary=plan.model_dump_json(), output=plan,
    )
    prompt = WorkPhase().prompt(state)
    assert "WORK PHASE" in prompt
    assert "RESULTS OF PREVIOUS PHASES" in prompt
    assert "write /app/out.txt" in prompt
    assert "final_result" in prompt
    assert "120s" in prompt  # fixed regime hard cap


def test_work_prompt_on_retry_carries_previous_attempt_error():
    state = _state()
    plan = PlanResult(goal="g", steps=["s"])
    state.results["plan"] = PhaseResult(
        status="done", summary=plan.model_dump_json(), output=plan,
    )
    state.results["work"] = PhaseResult(status="error", error="tool exploded")
    prompt = WorkPhase().prompt(state)
    assert "previous work attempt failed with" in prompt
    assert "tool exploded" in prompt


def test_review_prompt_never_repeats_task():
    phase = CommitPhase()
    # the task is in the system message (and in the resumed history), so the
    # review user prompt carries only the phase instructions
    no_history = _state(last_messages=[])
    with_history = _state(
        last_messages=[
            ModelRequest(parts=[TextPart("task text")]),
            ModelResponse(parts=[TextPart("answer")]),
        ]
    )
    for state in (no_history, with_history):
        prompt = phase.prompt(state)
        assert "Create hello.txt" not in prompt
        assert "REVIEW PHASE" in prompt


def test_emergency_prompt_is_the_rescue_instruction():
    prompt = EmergencyPhase().prompt(_state())
    assert "EMERGENCY" in prompt
    assert "Create hello.txt" not in prompt
