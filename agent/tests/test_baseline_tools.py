"""Baseline tool matrix contract (2026-09-07 slim-down, 2026-09-14 cut).

The packaged config.toml IS the baseline: recon is the ONLY custom tool
(batch 388fde — the orientation bundle was never adopted; the dev-arm tool
families were cut on 2026-09-14). This file pins the shipped phase x tool
matrix directly from the packaged config; the arm behavior lives in
test_toolsets.py.

Covers:
1. plan phase stays read-only (no bash/write/edit), work has the standard
   set + recon, review is the toolless relay
2. the registry routes exactly the baseline tools per phase
"""

from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.tools import get_tools


def _shipped_cfg():
    return load_config()


def test_registry_is_the_baseline_five():
    from shlepa_agent.tools import ALL_TOOLS

    assert set(ALL_TOOLS) == {"read", "write", "edit", "bash", "recon"}


def test_plan_matrix_is_read_only():
    cfg = _shipped_cfg()
    plan_tools = cfg.tool_policy.tools_for("plan", 1)
    read_only = {"read", "recon"}
    assert set(plan_tools) <= read_only
    assert not set(plan_tools) & {"bash", "write", "edit"}


def test_work_matrix_has_full_set():
    cfg = _shipped_cfg()
    work_tools = set(cfg.tool_policy.tools_for("work", 1))
    assert work_tools == {"read", "write", "edit", "bash", "recon"}


def test_review_is_toolless():
    cfg = _shipped_cfg()
    assert cfg.tool_policy.tools_for("review", 1) == []


def test_get_tools_routes_baseline_per_phase():
    cfg = _shipped_cfg()
    assert [t.name for t in get_tools(cfg, get_phase("plan").tools(cfg))] == [
        "read",
        "recon",
    ]
    assert [t.name for t in get_tools(cfg, get_phase("work").tools(cfg))] == [
        "read",
        "write",
        "edit",
        "bash",
        "recon",
    ]
    assert [t.name for t in get_tools(cfg, get_phase("review").tools(cfg))] == []
