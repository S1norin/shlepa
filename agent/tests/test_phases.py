"""t5: phase protocol, explore/commit phases, structured results.

Covers: PhaseResult JSON roundtrip, RunState.results, routing (explore:
done->None / budget|error->commit; commit: terminal), trimmed commit
history on synthetic message lists, and config-driven toolsets/limits.
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
from shlepa_agent.phases import (
    CommitPhase,
    ExplorePhase,
    PhaseResult,
    RunState,
    get_phase,
    trim_history,
)
from shlepa_agent.tools import AgentDeps


def _state(task="Create hello.txt with the exact content hello", last_messages=None):
    cfg = load_config()
    deps = AgentDeps(workdir=Path("/tmp"), cfg=cfg, clock=lambda: 0.0)
    model = SimpleNamespace(last_messages=last_messages if last_messages is not None else [])
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


def test_run_state_holds_one_result_per_phase():
    state = _state()
    state.results["explore"] = PhaseResult(status="budget", summary="cut off")
    state.results["commit"] = PhaseResult(status="done")
    assert state.cfg is state.deps.cfg
    assert state.results["explore"].status == "budget"
    assert state.cfg.agent.emergency == "commit"


# -- routing -----------------------------------------------------------------
def test_explore_route_done_is_terminal():
    state = _state()
    assert ExplorePhase().route(PhaseResult(status="done"), state) is None


def test_explore_route_budget_and_error_go_to_commit():
    state = _state()
    phase = ExplorePhase()
    assert phase.route(PhaseResult(status="budget", error="limit"), state) == "commit"
    assert phase.route(PhaseResult(status="error", error="boom"), state) == "commit"


def test_commit_phase_is_terminal():
    state = _state()
    assert CommitPhase().route(PhaseResult(status="done"), state) is None
    limits = CommitPhase().limits(state.cfg)
    assert limits.terminal is True
    assert ExplorePhase().limits(state.cfg).terminal is False


# -- commit history trimming -------------------------------------------------
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


# -- config-driven toolsets and limits ----------------------------------------
def test_phase_toolsets_from_config():
    cfg = load_config()
    assert CommitPhase().tools(cfg) == ["read", "write", "edit", "bash"]
    assert ExplorePhase().tools(cfg) == ["read", "write", "edit", "bash"]


def test_phase_limits_from_config():
    cfg = load_config()
    commit = CommitPhase().limits(cfg)
    assert commit.requests == 25
    assert commit.time == 80.0
    assert commit.reasoning_effort == "low"
    explore = ExplorePhase().limits(cfg)
    assert explore.requests == 90
    assert explore.time == 500.0
    assert explore.reasoning_effort is None


def test_registry_resolves_configured_phase_ids():
    cfg = load_config()
    assert isinstance(get_phase(cfg.agent.entry), ExplorePhase)
    assert isinstance(get_phase(cfg.agent.emergency), CommitPhase)
    try:
        get_phase("nope")
        assert False, "expected KeyError"
    except KeyError as e:
        assert "nope" in str(e)


# -- prompts -------------------------------------------------------------------
def test_explore_prompt_carries_phase_instructions_only():
    phase = ExplorePhase()
    prompt = phase.prompt(_state())
    assert "PHASE INSTRUCTIONS" in prompt
    # the task text lives in the system message now, not in the user prompt
    assert "Create hello.txt with the exact content hello" not in prompt


def test_commit_prompt_never_repeats_task():
    phase = CommitPhase()
    # the task is in the system message (and in the resumed history), so the
    # commit user prompt carries only the phase instructions
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
        assert "BUDGET EXHAUSTED" in prompt
