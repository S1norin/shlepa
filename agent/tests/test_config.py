"""Tests for the v2 agent config layer (config.toml + env overrides)."""

import pytest

from shlepa_agent.config import load_config


def test_agent_section_defaults():
    cfg = load_config()
    assert cfg.agent.entry == "explore"
    assert cfg.agent.emergency == "commit"
    assert cfg.agent.max_steps >= 8
    assert cfg.agent.temp == 0.2


def test_budget_values_match_v1_defaults():
    cfg = load_config()
    b = cfg.budget
    assert b.hard_time == 585.0
    assert b.soft_time == 500.0
    assert b.request_limit == 90
    assert b.token_budget == 300000
    assert b.max_tokens == 16384
    assert b.request_timeout == 180.0
    assert b.request_wall == 240.0


def test_tool_values_match_v1_defaults():
    cfg = load_config()
    assert cfg.tools.bash.enabled is True
    assert cfg.tools.bash.timeout == 120.0
    assert cfg.tools.bash.max_output == 16000
    assert cfg.tools.read_file.max_output == 16000
    for name in ("write_file", "append_file", "apply_diff"):
        assert cfg.tools.get(name).enabled is True


def test_unknown_tool_raises():
    cfg = load_config()
    with pytest.raises(KeyError):
        cfg.tools.get("nope")


def test_phase_values_match_v1():
    cfg = load_config()
    explore = cfg.phases["explore"]
    assert set(explore.tools) == {"bash", "read_file", "write_file", "append_file", "apply_diff"}
    assert explore.requests == 90
    assert explore.time == 500.0

    commit = cfg.phases["commit"]
    assert set(commit.tools) == {"bash", "read_file", "write_file"}
    assert commit.requests == 25
    assert commit.time == 80.0
    assert commit.reasoning_effort == "low"
    assert commit.max_retries == 2


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
    cfg = load_config()
    assert cfg.budget.hard_time == 600.0
    assert cfg.tools.bash.timeout == 90.0
    assert cfg.agent.temp == 0.1


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
