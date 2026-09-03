"""v3 loop-regime tests: the budgeted main phase -> terminal commit.

Covers the v3loop pipeline (shlepa_agent.v3loop): a normal main finish
ends the run with NO commit (v3 parity); a budget breach (soft/hard wall
clock, request limit, token budget) or a persistent model error hands off
to the terminal commit phase (capped at the remaining hard window, skipped
below 10s); a non-budget error ends the run without a commit. The commit
resumes the trimmed main history and sends [phases.commit]'s reasoning
effort under [v3loop].commit_request_limit.
"""

import asyncio
import json
import logging

import pytest

from stub_server import stub_state

TASK = "create hello.txt with the content hello"

# The v3 agent's COMMIT_PROMPT, verbatim (registered v3 agent, MLflow model
# version 3 / run ee78c24c). prompts/v3commit.md must stay byte-identical.
V3_COMMIT_PROMPT = (
    "\u26a0\ufe0f BUDGET EXHAUSTED. Stop exploring. Write the final deliverable NOW to the exact "
    "path with the exact format using only the information you already have. If the deliverable "
    "file already exists, verify it exactly once (re-read / jq / wc -l) and correct it if wrong. "
    "Then finish with one short line. Use only the tools needed to write and verify the file."
)


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


def _cfg(
    tmp_path,
    soft_time=500.0,
    hard_time=585.0,
    request_limit=90,
    token_budget=300_000,
    commit_time_cap=80.0,
    commit_request_limit=25,
    request_wall=240.0,
):
    p = tmp_path / "cfg.toml"
    p.write_text(
        f"""\
[agent]
loop = "v3"
temp = 0.6
send_temp = false

[budget]
max_tokens = 16384
request_timeout = 30.0

[tools.bash]
enabled = true
timeout = 5.0
max_timeout = 5.0
max_output = 4000
[tools.read]
enabled = true
[tools.write]
enabled = true
[tools.edit]
enabled = true

[phases.main]
tools = ["read", "write", "edit", "bash"]
requests = {request_limit}
max_retries = 0

[phases.commit]
tools = ["read", "write", "edit", "bash"]
requests = {commit_request_limit}
reasoning_effort = "low"
max_retries = 0

[v3loop]
soft_time = {soft_time}
hard_time = {hard_time}
request_limit = {request_limit}
token_budget = {token_budget}
commit_time_cap = {commit_time_cap}
commit_request_limit = {commit_request_limit}
request_wall = {request_wall}
""",
        encoding="utf-8",
    )
    from shlepa_agent.config import load_config

    return load_config(p)


def _run(monkeypatch, stub_openai, tmp_path, agent_cfg):
    from shlepa_agent import v3loop

    monkeypatch.setenv("OPENAI_BASE_URL", stub_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    monkeypatch.setenv("LOCAL_AGENT_WORKDIR", str(tmp_path))
    return asyncio.run(v3loop.run_prompt(TASK, agent_cfg=agent_cfg))


def _status(events):
    done = [e for e in events if e.get("event") == "agent_done" and "status" in e]
    return done[-1]["status"] if done else None


def _age_model(monkeypatch, seconds):
    """Wrap _make_model so the returned model's clock starts aged."""
    import shlepa_agent.v3loop as v3loop

    real_factory = v3loop._make_model

    def aged_factory(model_name, provider, cfg):
        model = real_factory(model_name, provider, cfg)
        model.t0 -= seconds
        return model

    monkeypatch.setattr(v3loop, "_make_model", aged_factory)


def _tool_step():
    return {"tool_call": {"name": "bash", "arguments": {"command": "ls"}}}


def _usage_step():
    """A tool-call step that also reports usage (the stub's opt-in knob)."""
    return {
        **_tool_step(),
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# -- prompt files (AC: main.md sections, v3commit.md verbatim) --------------
def test_prompt_files_match_v3():
    from shlepa_agent.template import load_prompt

    main_md = load_prompt("main.md")
    for section in ("PROTOCOL", "FORMAT DISCIPLINE", "CODE FIX TASKS", "BUDGET"):
        assert section in main_md, f"main.md lost the {section} section"
    # Spot-check that the v3 text survived the adaptation verbatim.
    assert "Read the task. Extract the exact deliverable spec" in main_md
    assert "Copy strings, hashes, timestamps, and commands verbatim" in main_md
    assert "Fix the root cause with the smallest correct change" in main_md
    assert 'If you receive a "BUDGET EXHAUSTED" message:' in main_md
    assert load_prompt("v3commit.md") == V3_COMMIT_PROMPT


# -- normal finish (AC: done, no commit) -------------------------------------
def test_main_finsihes_normally_without_commit(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [{"final": "wrote hello.txt"}]
    output = _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))
    assert output == "wrote hello.txt"
    assert _status(events) == "done"
    assert not [e for e in events if e.get("event") == "commit"]
    assert not [e for e in events if e.get("event") == "budget"]
    assert len(stub_state["bodies"]) == 1
    # phase start/done events for the single open main phase
    assert [
        e for e in events if e.get("event") == "phase" and e.get("id") == "main" and e.get("start")
    ]
    done = [e for e in events if e.get("event") == "phase_done" and e.get("id") == "main"]
    assert done and done[0]["status"] == "done"


# -- budget breach -> commit (AC: budget event, commit start+done, budget) ---
def test_soft_breach_hands_off_to_commit(monkeypatch, stub_openai, tmp_path, events):
    # 60s in at the first request: past soft (50s), well under hard (200s).
    _age_model(monkeypatch, 60.0)
    stub_state["script"] = [{"final": "COMMIT: wrote hello.txt"}]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path, soft_time=50.0, hard_time=200.0))
    assert _status(events) == "budget"
    budget = [e for e in events if e.get("event") == "budget"]
    assert budget and budget[0]["reason"] == "usage_or_time"
    commits = [e for e in events if e.get("event") == "commit"]
    assert commits[0].get("start") is True
    assert commits[0].get("phase") == "commit"
    assert any(e.get("done") is True for e in commits)
    # The main request was never sent (the gate fires first); the commit
    # ran once on an empty history -> ORIGINAL TASK re-stated in the prompt.
    assert len(stub_state["bodies"]) == 1
    last = stub_state["bodies"][0]["messages"][-1]
    assert "BUDGET EXHAUSTED" in last["content"]
    assert "ORIGINAL TASK" in last["content"]


def test_hard_breach_skips_commit(monkeypatch, stub_openai, tmp_path, events):
    # Past the hard window: the remaining commit window is 0s (< 10s) ->
    # the commit is skipped, the run still ends as "budget".
    _age_model(monkeypatch, 120.0)
    stub_state["script"] = [{"final": "never sent"}]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path, soft_time=50.0, hard_time=100.0))
    assert _status(events) == "budget"
    assert [e for e in events if e.get("event") == "commit" and e.get("skipped") is True]
    assert not [e for e in events if e.get("event") == "commit" and e.get("start")]
    assert len(stub_state["bodies"]) == 0


def test_commit_skipped_with_less_than_10s_left(monkeypatch, stub_openai, tmp_path, events):
    # A request-limit breach at hard_time - 5s: only 5s of the hard window
    # remain -> the commit is skipped (below COMMIT_MIN_CAP_S).
    _age_model(monkeypatch, 95.0)
    stub_state["script"] = [_tool_step(), {"final": "never sent"}]
    _run(
        monkeypatch,
        stub_openai,
        tmp_path,
        _cfg(tmp_path, soft_time=500.0, hard_time=100.0, request_limit=1),
    )
    assert _status(events) == "budget"
    budget = [e for e in events if e.get("event") == "budget"]
    assert budget and budget[0]["reason"] == "usage_or_time"
    assert [e for e in events if e.get("event") == "commit" and e.get("skipped") is True]
    assert not [e for e in events if e.get("event") == "commit" and e.get("start")]
    assert len(stub_state["bodies"]) == 1  # only main request 1 was sent


# -- UsageLimits breaches -> commit (AC: request limit + token budget) -------
def test_request_limit_breach_triggers_commit(monkeypatch, stub_openai, tmp_path, events):
    # Open tool-call loop: the limit (2) is hit before main request 3.
    stub_state["script"] = [
        _tool_step(),
        _tool_step(),
        {"final": "COMMIT: wrote hello.txt"},
    ]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path, request_limit=2))
    assert _status(events) == "budget"
    budget = [e for e in events if e.get("event") == "budget"]
    assert budget and "request_limit" in budget[0].get("detail", "")
    assert len(stub_state["bodies"]) == 3  # 2 main + 1 commit
    commits = [e for e in events if e.get("event") == "commit"]
    assert commits[0].get("start") is True
    assert any(e.get("done") is True for e in commits)


def test_token_budget_breach_triggers_commit(monkeypatch, stub_openai, tmp_path, events):
    # 15 tokens per reported response, budget 30: the breach lands after
    # main response 3 (45 > 30) in check_tokens. Tool-call responses carry
    # usage only via the opt-in "usage" knob (the stub default is none).
    stub_state["script"] = [
        _usage_step(),
        _usage_step(),
        _usage_step(),
        {"final": "COMMIT: wrote hello.txt"},
    ]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path, token_budget=30))
    assert _status(events) == "budget"
    budget = [e for e in events if e.get("event") == "budget"]
    assert budget and "total_tokens_limit" in budget[0].get("detail", "")
    assert len(stub_state["bodies"]) == 4  # 3 main + 1 commit


# -- commit run details (AC: trimmed history + reasoning_effort + limit) -----
def test_commit_resumes_history_and_sends_settings(monkeypatch, stub_openai, tmp_path, events):
    stub_state["script"] = [_usage_step(), _usage_step(), _usage_step(), {"final": "committed"}]
    _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path, token_budget=30))
    main_bodies = stub_state["bodies"][:3]
    commit_body = stub_state["bodies"][3]
    # [phases.commit].reasoning_effort is sent on the commit request only.
    assert commit_body.get("reasoning_effort") == "low"
    assert all("reasoning_effort" not in b for b in main_bodies)
    # The commit resumes the trimmed main conversation (token breach: the
    # offending response is not in the history, so it ends on a tool return).
    msgs = commit_body["messages"]
    assert msgs[0]["role"] in ("system", "developer")
    assert "PROTOCOL" in msgs[0]["content"]  # main's system prompt
    assert msgs[1] == main_bodies[0]["messages"][1]  # the task user message
    assert [m["role"] for m in msgs[1:-1]] == ["user", "assistant", "tool", "assistant", "tool"]
    # The commit prompt is the v3 COMMIT_PROMPT, verbatim.
    assert msgs[-1] == {"role": "user", "content": V3_COMMIT_PROMPT}
    # The commit start event reports the resumed history size (5 model
    # objects: the system prompt is folded into the first user request).
    start = next(e for e in events if e.get("event") == "commit" and e.get("start"))
    assert start["history_messages"] == 5


def test_commit_request_limit_enforced(monkeypatch, stub_openai, tmp_path, events):
    # Main breaches on its request limit (2); the commit loops on tool
    # calls until its own commit_request_limit (3) is hit.
    stub_state["script"] = [_tool_step(), _tool_step(), _tool_step(), _tool_step()]
    _run(
        monkeypatch,
        stub_openai,
        tmp_path,
        _cfg(tmp_path, request_limit=2, commit_request_limit=3),
    )
    assert _status(events) == "budget"
    assert len(stub_state["bodies"]) == 5  # 2 main + 3 commit, then the limit
    done = [e for e in events if e.get("event") == "commit" and e.get("done")]
    assert done and "UsageLimitExceeded" in done[0].get("error", "")


# -- non-budget error (AC: error status, no commit) ---------------------------
def test_non_budget_error_ends_without_commit(monkeypatch, stub_openai, tmp_path, events):
    import shlepa_agent.v3loop as v3loop

    def boom(model, cfg, instrument=False):
        raise RuntimeError("simulated main failure")

    monkeypatch.setattr(v3loop, "build_main_agent", boom)
    stub_state["script"] = [{"final": "never sent"}]
    output = _run(monkeypatch, stub_openai, tmp_path, _cfg(tmp_path))
    assert output == ""
    assert _status(events) == "error"
    assert any(e.get("event") == "agent_error" for e in events)
    assert not [e for e in events if e.get("event") == "budget"]
    assert not [e for e in events if e.get("event") == "commit"]
    assert len(stub_state["bodies"]) == 0


# -- arm axis (AC: the arm's toolset reaches the main phase) -------------------
def test_arm_mutation_reaches_main_tools(monkeypatch, stub_openai, tmp_path, events):
    monkeypatch.setenv("AGENT_TOOLSET", "+smart-grep")
    cfg = _cfg(tmp_path)  # load_config applies the arm mutation
    assert cfg.arm == "+smart-grep"
    assert "code_search" in cfg.phases["main"].tools
    stub_state["script"] = [{"final": "wrote hello.txt"}]
    output = _run(monkeypatch, stub_openai, tmp_path, cfg)
    assert output == "wrote hello.txt"
    assert _status(events) == "done"
    body = stub_state["bodies"][0]
    tool_names = {t["function"]["name"] for t in body.get("tools", [])}
    assert "code_search" in tool_names
    # The main phase is free text: no typed-output (final_result) tool.
    assert "final_result" not in tool_names
    # The arm's tool notes render into the system message.
    system = body["messages"][0]
    assert "code_search" in system["content"]
    # MainPhase carries no output type.
    from shlepa_agent.v3loop import MainPhase

    assert MainPhase.output_type is None


# -- agent_start log contract (AC: v3loop fields) ------------------------------
def test_agent_start_carries_v3loop_budget(monkeypatch, stub_openai, tmp_path, events):
    cfg = _cfg(
        tmp_path,
        soft_time=123.0,
        hard_time=456.0,
        request_limit=42,
        token_budget=999,
        commit_time_cap=33.0,
        commit_request_limit=7,
        request_wall=77.0,
    )
    stub_state["script"] = [{"final": "ok"}]
    _run(monkeypatch, stub_openai, tmp_path, cfg)
    start = next(e for e in events if e.get("event") == "agent_start")
    assert start["loop"] == "v3"
    assert start["soft_time"] == pytest.approx(123.0)
    assert start["hard_time"] == pytest.approx(456.0)
    assert start["request_limit"] == 42
    assert start["token_budget"] == 999
    assert start["commit_time_cap"] == pytest.approx(33.0)
    assert start["commit_request_limit"] == 7
    assert start["request_wall"] == pytest.approx(77.0)
