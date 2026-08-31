"""Tests for the v2 agent config layer (config.toml + env overrides)."""

import pytest

from shlepa_agent.config import load_config


def test_agent_section_defaults():
    cfg = load_config()
    # packaged pipeline is budget-driven: zero/empty = "derive from T"
    assert cfg.agent.entry == ""
    assert cfg.agent.emergency == "emergency"
    assert cfg.agent.commit_deadline == 0.0
    assert cfg.agent.max_steps == 0
    assert cfg.agent.temp == 0.2


def test_build_budget_derives_v5_world_for_600s(monkeypatch):
    from shlepa_agent.budget import TIME_ENV_CANDIDATES
    from shlepa_agent.config import build_budget

    for key in TIME_ENV_CANDIDATES + ("TASK_DIR", "SHLEPA_BUDGET_T_FALLBACK"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    budget = build_budget(cfg, "a task with no explicit limit")
    assert budget.T == 600.0
    assert budget.source in ("fallback", "config:default")
    # v5 fixed regime: caps are constants, only hard follows T
    assert budget.hard == pytest.approx(585.0)
    assert budget.margin == pytest.approx(15.0)
    assert budget.plan == pytest.approx(60.0)
    assert budget.work == pytest.approx(120.0)
    assert budget.review == pytest.approx(45.0)
    assert budget.bash_cap == pytest.approx(30.0)
    assert budget.llm_wall == pytest.approx(180.0)
    # derived pipeline values the runner uses: a full 225s cycle fits 585s
    full_cycle = budget.plan + budget.work + budget.review
    assert (cfg.agent.entry or ("plan" if budget.hard >= full_cycle else "work")) == "plan"
    deadline = min(full_cycle, budget.hard)
    assert deadline == pytest.approx(225.0)


def test_budget_values_match_v1_defaults():
    cfg = load_config()
    b = cfg.budget
    # reference values for the default 600s task (logging + legacy backstop)
    assert b.hard_time == 585.0
    assert b.soft_time == 500.0
    assert b.t_fallback == 600.0
    assert b.max_tokens == 16384
    assert b.request_timeout == 180.0
    assert b.request_wall == 180.0


def test_tool_values():
    cfg = load_config()
    assert cfg.tools.bash.enabled is True
    assert cfg.tools.bash.timeout == 30.0
    assert cfg.tools.bash.max_timeout == 120.0
    assert cfg.tools.bash.max_output == 16000
    assert cfg.tools.read.enabled is True
    assert cfg.tools.read.max_limit == 100
    assert cfg.tools.read.max_output == 4000
    for name in ("write", "edit"):
        assert cfg.tools.get(name).enabled is True


def test_unknown_tool_raises():
    cfg = load_config()
    with pytest.raises(KeyError):
        cfg.tools.get("nope")


def test_phase_values_4_phase_pipeline():
    cfg = load_config()
    assert set(cfg.phases) == {"plan", "work", "commit", "emergency"}

    plan = cfg.phases["plan"]
    assert set(plan.tools) == {"read", "write", "edit", "bash"}
    assert plan.requests == 25
    assert plan.time is None  # hard cap derived from the adaptive budget
    assert plan.soft_time == 45.0  # advisory
    assert plan.soft_tokens == 15000  # advisory
    assert plan.max_retries == 1

    work = cfg.phases["work"]
    assert set(work.tools) == {"read", "write", "edit", "bash"}
    assert work.requests == 100
    assert work.time is None  # hard cap derived from the adaptive budget
    assert work.soft_time == 150.0  # advisory
    assert work.soft_tokens == 80000  # advisory
    assert work.max_retries == 1

    commit = cfg.phases["commit"]
    assert set(commit.tools) == {"read", "write", "edit", "bash"}
    assert commit.requests == 20
    assert commit.time is None  # runs until the global hard_time
    assert commit.soft_time == 45.0
    assert commit.soft_tokens == 20000
    assert commit.reasoning_effort == "low"
    assert commit.max_retries == 0

    emergency = cfg.phases["emergency"]
    assert set(emergency.tools) == {"read", "write", "edit", "bash"}
    assert emergency.requests == 20
    assert emergency.time is None  # runs until the global hard_time
    assert emergency.reasoning_effort == "low"
    assert emergency.max_retries == 0


def test_template_blocks():
    cfg = load_config()
    blocks = cfg.template.blocks
    assert blocks[:2] == ["system", "tools"]
    for block in ("task", "extra", "previous_results", "phase_prompt", "output_schema", "note"):
        assert block in blocks, block
    # every non-system block has a wrapper entry (may be empty strings)
    for block in blocks[2:]:
        assert block in cfg.template.wrappers, block


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("SHLEPA_BUDGET_HARD_TIME", "600")
    monkeypatch.setenv("SHLEPA_BASH_TIMEOUT", "90")
    monkeypatch.setenv("SHLEPA_TEMP", "0.1")
    monkeypatch.setenv("SHLEPA_COMMIT_DEADLINE", "500")
    cfg = load_config()
    assert cfg.budget.hard_time == 600.0
    assert cfg.tools.bash.timeout == 90.0
    assert cfg.agent.temp == 0.1
    assert cfg.agent.commit_deadline == 500.0


def test_invalid_env_override_ignored(monkeypatch):
    monkeypatch.setenv("SHLEPA_BUDGET_HARD_TIME", "not-a-number")
    cfg = load_config()
    assert cfg.budget.hard_time == 585.0


def test_custom_path(tmp_path):
    import shutil

    from shlepa_agent.config import DEFAULT_CONFIG_PATH

    custom = tmp_path / "cfg.toml"
    shutil.copyfile(DEFAULT_CONFIG_PATH, custom)
    cfg = load_config(custom)
    assert cfg.budget.hard_time == 585.0
