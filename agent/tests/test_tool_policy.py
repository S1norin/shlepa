"""Tool policy layer (v6-rewrite): the single phase x iteration matrix.

The [tool_policy] section of config.toml is the single source of tool
availability. This test pins the shipped matrix, the resolver semantics
(per-iteration overrides, legacy fallback) and the disabled-phase list.
"""

from __future__ import annotations

import pytest

from shlepa_agent.budget import FINALIZE_RESERVE, finalize_reserve
from shlepa_agent.config import ENV_OVERRIDES, ToolPolicy, load_config


def _shipped_cfg():
    return load_config()


class TestShippedMatrix:
    def test_plan_matrix(self):
        # 2026-09-07 slim-down: recon is the only custom tool in the
        # baseline (the research families live on as dev arms, toolsets.py)
        cfg = _shipped_cfg()
        assert cfg.tool_policy.tools_for("plan", 1) == ["read", "recon"]

    def test_work_matrix(self):
        cfg = _shipped_cfg()
        assert cfg.tool_policy.tools_for("work", 1) == [
            "read", "write", "edit", "bash", "recon",
        ]

    def test_review_has_no_tools(self):
        cfg = _shipped_cfg()
        assert cfg.tool_policy.tools_for("review", 1) == []

    def test_disabled_phases(self):
        cfg = _shipped_cfg()
        for pid in ("repair", "salvage", "emergency", "commit"):
            assert cfg.tool_policy.is_disabled(pid), pid

    def test_matrix_identical_across_cycles(self):
        cfg = _shipped_cfg()
        for pid in ("plan", "work", "review"):
            assert cfg.tool_policy.tools_for(pid, 1) == cfg.tool_policy.tools_for(pid, 2)


class TestResolverSemantics:
    def test_per_iteration_override_beats_phase_entry(self):
        pol = ToolPolicy(
            phases={"work": ["read", "write"], "work_c2": ["read", "write", "edit"]}
        )
        assert pol.tools_for("work", 1) == ["read", "write"]
        assert pol.tools_for("work", 2) == ["read", "write", "edit"]
        # the override only affects its own iteration
        assert pol.tools_for("work", 3) == ["read", "write"]

    def test_fallback_to_phase_tools(self):
        pol = ToolPolicy(phases={})
        assert pol.tools_for("plan", 1, fallback=["read"]) == ["read"]
        assert pol.tools_for("plan", 1) == []

    def test_cycle_one_clamps_below_one(self):
        pol = ToolPolicy(phases={"work": ["read"], "work_c1": ["read", "edit"]})
        assert pol.tools_for("work", 0) == ["read", "edit"]


class TestCycleKnob:
    def test_default_two_cycles(self):
        cfg = _shipped_cfg()
        assert cfg.agent.max_cycles == 2

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHLEPA_MAX_CYCLES", "3")
        cfg = load_config()
        assert cfg.agent.max_cycles == 3

    def test_env_override_invalid_keeps_file(self, monkeypatch):
        monkeypatch.setenv("SHLEPA_MAX_CYCLES", "not-a-number")
        cfg = load_config()
        assert cfg.agent.max_cycles == 2


class TestRemovedA0Knobs:
    def test_route_plan_timeout_gone(self):
        assert "SHLEPA_ROUTE_PLAN_TIMEOUT" not in ENV_OVERRIDES

    def test_handoff_gone(self):
        assert "SHLEPA_HANDOFF" not in ENV_OVERRIDES

    def test_agent_section_fields_gone(self):
        cfg = _shipped_cfg()
        assert not hasattr(cfg.agent, "route_plan_failure")
        assert not hasattr(cfg.agent, "handoff")


class TestFinalizeReserve:
    def test_default_is_15s(self):
        assert FINALIZE_RESERVE == 15.0
        assert finalize_reserve() == 15.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("SHLEPA_FINALIZE_RESERVE", "7")
        assert finalize_reserve() == 7.0


@pytest.mark.parametrize("pid", ["plan", "work", "review"])
def test_phase_sections_still_exist_for_disabled_and_new_phases(pid):
    """[phases.*] sections stay (time/requests) even when tools moved out."""
    cfg = _shipped_cfg()
    assert pid in cfg.phases
