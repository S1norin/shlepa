"""Tests for the v2 agent config layer (config.toml + env overrides)."""

import pytest

from shlepa_agent.config import load_config


def test_agent_section_defaults():
    cfg = load_config()
    # v5: no time horizon — entry is always "plan" by default, no deadline
    assert cfg.agent.entry == ""
    assert cfg.agent.emergency == "emergency"
    assert cfg.agent.max_steps == 0
    assert cfg.agent.temp == 0.6
    assert cfg.agent.send_temp is False  # default: endpoint decides


def test_budget_values():
    cfg = load_config()
    b = cfg.budget
    # per-request caps only: the phase caps are constants in budget.py,
    # there is no T / hard_time / soft_time / t_fallback / request_wall
    assert b.max_tokens == 16384
    assert b.request_timeout == 180.0
    assert not hasattr(b, "hard_time")
    assert not hasattr(b, "t_fallback")


def test_tool_values():
    cfg = load_config()
    assert cfg.tools.bash.enabled is True
    assert cfg.tools.bash.timeout == 30.0
    assert cfg.tools.bash.max_timeout == 30.0
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
    assert set(cfg.phases) == {"plan", "work", "salvage", "commit", "emergency"}

    plan = cfg.phases["plan"]
    # v6: read-only exploration surface; bash/write/edit structurally absent
    assert set(plan.tools) == {"read", "recon", "search"}
    assert plan.requests == 25
    assert plan.time is None  # cap = regime constant (budget.py, 30s)
    assert plan.soft_time == 25.0  # advisory, under the 30s cap
    assert plan.soft_tokens == 15000  # advisory
    assert plan.max_retries == 1

    work = cfg.phases["work"]
    # v6: recon + search join the work toolset (structured exploration).
    assert set(work.tools) == {"read", "write", "edit", "bash", "recon", "search"}
    assert work.requests == 100
    assert work.time is None  # cap = regime constant (budget.py)
    assert work.soft_time == 105.0  # advisory, under the 120s cap
    assert work.soft_tokens is None  # no token note for work
    assert work.max_retries == 1

    commit = cfg.phases["commit"]
    # v6 (w2-4): VERIFY is read-only (repair is a separate phase, w2-5).
    assert set(commit.tools) == {"read", "search"}
    assert commit.requests == 20
    assert commit.time is None  # cap = regime constant (budget.py)
    assert commit.soft_time == 35.0  # advisory, under the 45s cap
    assert commit.soft_tokens == 20000
    assert commit.reasoning_effort == "low"
    assert commit.max_retries == 0

    emergency = cfg.phases["emergency"]
    assert set(emergency.tools) == {"read", "write", "edit", "bash"}
    assert emergency.requests == 20
    assert emergency.time is None
    assert emergency.reasoning_effort == "low"
    assert emergency.max_retries == 0


def test_salvage_phase_config():
    # v6 (w2-3): write-only rescue, explicit 30 s cap, never retried.
    cfg = load_config()
    salvage = cfg.phases["salvage"]
    assert set(salvage.tools) == {"write"}
    assert salvage.requests == 5
    assert salvage.time == 30.0
    assert salvage.max_retries == 0


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
    monkeypatch.setenv("SHLEPA_BUDGET_MAX_TOKENS", "999")
    monkeypatch.setenv("SHLEPA_BASH_TIMEOUT", "90")
    monkeypatch.setenv("SHLEPA_TEMP", "0.1")
    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    cfg = load_config()
    assert cfg.budget.max_tokens == 999
    assert cfg.tools.bash.timeout == 90.0
    assert cfg.agent.temp == 0.1
    assert cfg.agent.send_temp is True


def test_send_temp_env_override(monkeypatch):
    monkeypatch.setenv("SHLEPA_SEND_TEMP", "1")
    assert load_config().agent.send_temp is True
    monkeypatch.setenv("SHLEPA_SEND_TEMP", "0")
    assert load_config().agent.send_temp is False
    monkeypatch.setenv("SHLEPA_SEND_TEMP", "garbage")
    assert load_config().agent.send_temp is False  # invalid: ignored


def test_temp_env_override_independent_of_send(monkeypatch):
    monkeypatch.setenv("SHLEPA_TEMP", "0.9")
    cfg = load_config()
    assert cfg.agent.temp == 0.9
    assert cfg.agent.send_temp is False


def test_invalid_env_override_ignored(monkeypatch):
    monkeypatch.setenv("SHLEPA_BUDGET_MAX_TOKENS", "not-a-number")
    cfg = load_config()
    assert cfg.budget.max_tokens == 16384


def test_plan_cap_env_override(monkeypatch):
    # v6 knob: the plan cap defaults to the regime constant (30s) and is
    # env-overridable via SHLEPA_PLAN_TIME (an explicit phases.plan.time).
    assert load_config().phases["plan"].time is None
    monkeypatch.setenv("SHLEPA_PLAN_TIME", "45")
    cfg = load_config()
    assert cfg.phases["plan"].time == 45.0
    monkeypatch.setenv("SHLEPA_PLAN_TIME", "not-a-number")
    assert load_config().phases["plan"].time is None  # invalid: ignored


def test_search_tool_env_toggle(monkeypatch):
    assert load_config().tools.search.enabled is True
    monkeypatch.setenv("SHLEPA_SEARCH", "0")
    assert load_config().tools.search.enabled is False
    monkeypatch.setenv("SHLEPA_SEARCH", "1")
    assert load_config().tools.search.enabled is True
    monkeypatch.setenv("SHLEPA_SEARCH", "garbage")
    assert load_config().tools.search.enabled is True  # invalid: ignored


def test_v6_routing_and_handoff_knobs(monkeypatch):
    # v6 A/B knobs: SHLEPA_ROUTE_PLAN_TIMEOUT (work|commit) and
    # SHLEPA_HANDOFF (partial|off) — each appears in ENV_OVERRIDES with a
    # type, ships with its v6 default, and overrides cleanly.
    from shlepa_agent.config import ENV_OVERRIDES, _env_bool

    assert ENV_OVERRIDES["SHLEPA_ROUTE_PLAN_TIMEOUT"] == ("agent.route_plan_failure", str)
    assert ENV_OVERRIDES["SHLEPA_HANDOFF"] == ("agent.handoff", str)
    assert ENV_OVERRIDES["SHLEPA_PLAN_TIME"] == ("phases.plan.time", float)
    assert ENV_OVERRIDES["SHLEPA_SEARCH"] == ("tools.search.enabled", _env_bool)

    cfg = load_config()  # v6 defaults
    assert cfg.agent.route_plan_failure == "work"
    assert cfg.agent.handoff == "partial"

    monkeypatch.setenv("SHLEPA_ROUTE_PLAN_TIMEOUT", "commit")
    monkeypatch.setenv("SHLEPA_HANDOFF", "off")  # A0: the v5 routes
    cfg = load_config()
    assert cfg.agent.route_plan_failure == "commit"
    assert cfg.agent.handoff == "off"

    monkeypatch.setenv("SHLEPA_ROUTE_PLAN_TIMEOUT", "garbage")
    cfg = load_config()
    assert cfg.agent.route_plan_failure == "garbage"  # the runner falls
    # back to the v6 default (work) for unknown values


def test_custom_path(tmp_path):
    import shutil

    from shlepa_agent.config import DEFAULT_CONFIG_PATH

    custom = tmp_path / "cfg.toml"
    shutil.copyfile(DEFAULT_CONFIG_PATH, custom)
    cfg = load_config(custom)
    assert cfg.budget.max_tokens == 16384
