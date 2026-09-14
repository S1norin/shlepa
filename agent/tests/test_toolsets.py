"""Tests for named toolset arms (AGENT_TOOLSET, agent/shlepa_agent/toolsets.py).

The packaged config.toml IS the baseline (2026-09-07 slim-down, extended by
the 2026-09-14 cut that removed the dev-arm tool families
search/code_search/file_outline/log_triage entirely): recon is the ONLY
custom tool (plan read+recon, work standard set + recon), toolless review
relay, disabled phases (commit/repair/salvage/emergency) never routed.
The surviving arms only rearrange baseline tools: +recon is a no-op (recon
is baseline) and read-only (read/write/edit + recon, no bash). An invalid
AGENT_TOOLSET value is ignored, never a crash.

All matrix assertions use the EFFECTIVE tool list
(``get_phase(id).tools(cfg)`` — [tool_policy] over the legacy lists), the
same source the runner routes with.
"""

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.runner import _system_prompt
from shlepa_agent.tools import get_tools
from shlepa_agent.toolsets import (
    ARM_BASELINE,
    ARM_READONLY,
    ARM_RECON,
    KNOWN_ARMS,
    apply_arm,
    resolve_arm,
)

# The four phases the test matrix covers: the active plan/work/review trio
# plus the disabled legacy emergency (never routed, but its prompt still
# renders). commit/repair/salvage are disabled too; the "disabled phases
# stay untouched" checks cover them via the policy snapshot.
PHASES = ("plan", "work", "review", "emergency")
TASK = "TASK"

#: The effective baseline matrix (config.toml [tool_policy], 2026-09-07
#: slim-down: recon is the only custom tool). Arm mutations are diffs
#: against this: +recon dedupes to a no-op, read-only replaces the tooled
#: phases' lists, and the toolless review stays toolless under every arm.
BASE_PLAN = ["read", "recon"]
BASE_WORK = ["read", "write", "edit", "bash", "recon"]
BASE_REVIEW = []
BASE_EMERGENCY = ["read", "write", "edit", "bash"]
BASE_MATRIX = {
    "plan": BASE_PLAN,
    "work": BASE_WORK,
    "review": BASE_REVIEW,
    "emergency": BASE_EMERGENCY,
}

#: Disabled phases (config.toml [tool_policy].disabled): never routed, so
#: arm mutations must leave their policy entries byte-identical.
DISABLED_POLICY = {
    "commit": ["read"],
    "repair": ["read", "edit"],
    "salvage": ["write"],
}


def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)


def _eff(cfg, phase_id: str) -> list[str]:
    """The effective tool list the runner routes with for one phase."""
    return list(get_phase(phase_id).tools(cfg))


def _disabled_snapshot(cfg) -> dict[str, list[str]]:
    return {p: list(cfg.tool_policy.phases[p]) for p in DISABLED_POLICY}


# ---------------------------------------------------------------------------
# resolve_arm
# ---------------------------------------------------------------------------


def test_resolve_arm_returns_known_names():
    for arm in KNOWN_ARMS:
        assert resolve_arm(arm) == arm


def test_resolve_arm_strips_whitespace():
    assert resolve_arm("  +recon  ") == ARM_RECON
    assert resolve_arm("\nbaseline\n") == ARM_BASELINE


def test_resolve_arm_unknown_raises():
    for value in ("", "banana", "+sifs", "smart-grep", "BASELINE"):
        with pytest.raises(ValueError, match="unknown toolset arm"):
            resolve_arm(value)


# ---------------------------------------------------------------------------
# apply_arm (direct, no env)
# ---------------------------------------------------------------------------


def test_apply_arm_baseline_is_a_noop():
    cfg = load_config()
    snapshot = {p: _eff(cfg, p) for p in PHASES}
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_BASELINE)
    assert cfg.arm == ARM_BASELINE
    # the packaged config.toml IS the baseline: recon on
    assert cfg.tools.recon.enabled is True
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == snapshot[phase_id]
    assert _disabled_snapshot(cfg) == disabled_before


# ---------------------------------------------------------------------------
# env wiring (AGENT_TOOLSET)
# ---------------------------------------------------------------------------


def test_env_arm_baseline_is_the_packaged_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_BASELINE)
    cfg = load_config()
    # baseline is a no-op: the packaged config stays byte-identical
    assert cfg.arm == ARM_BASELINE
    assert cfg.tools.recon.enabled is True
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id]


def test_env_arm_invalid_is_ignored_never_crashes(monkeypatch):
    _clear(monkeypatch)
    for value in ("banana", "+sifs", "smart-grep"):
        monkeypatch.setenv("AGENT_TOOLSET", value)
        cfg = load_config()
        # an unknown arm is ignored: the packaged baseline stays
        assert cfg.arm == ARM_BASELINE, value
        assert cfg.tools.recon.enabled is True, value
        for phase_id in PHASES:
            assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id], value


def test_env_unset_defaults_to_baseline(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert cfg.arm == ARM_BASELINE
    # the baseline ships recon only
    assert cfg.tools.recon.enabled is True
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id]


# ---------------------------------------------------------------------------
# the +recon arm (recon is baseline now: the arm is a no-op)
# ---------------------------------------------------------------------------


def test_apply_arm_recon_is_a_noop():
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_RECON)
    assert cfg.arm == ARM_RECON
    assert cfg.tools.recon.enabled is True
    # recon is already wired in plan/work (deduped); the toolless review
    # stays toolless; disabled phases are never touched
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id], phase_id
    assert _disabled_snapshot(cfg) == disabled_before


def test_env_arm_recon_uses_tool_prompt_variant(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_RECON)
    cfg = load_config()
    assert cfg.arm == ARM_RECON
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, _eff(cfg, phase_id))]
        assert names == BASE_MATRIX[phase_id]
        prompt = _system_prompt(cfg, phase, TASK)
        if phase_id in ("plan", "work"):
            # every active tooled phase renders the tool variant
            assert "RECON TOOL" in prompt
            assert "RECON SCRIPT" not in prompt
            assert "python3 tools/recon.py" not in prompt
        elif phase_id == "emergency":
            # the disabled emergency has no recon tool: script variant
            assert "RECON SCRIPT" in prompt
            assert "RECON TOOL" not in prompt
        else:
            # the toolless review gets no recon block at all
            assert "RECON TOOL" not in prompt
            assert "RECON SCRIPT" not in prompt
            assert "python3 tools/recon.py" not in prompt


def test_baseline_prompt_uses_tool_variant_in_tooled_phases(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    for phase_id in PHASES:
        prompt = _system_prompt(cfg, get_phase(phase_id), TASK)
        assert "{recon}" not in prompt  # the placeholder always resolves
        if phase_id in ("plan", "work"):
            assert "RECON TOOL" in prompt
            assert "RECON SCRIPT" not in prompt
            assert "python3 tools/recon.py" not in prompt
            assert "RECON TOOL" in prompt.split("ROLE AND PHASES")[0]
        elif phase_id == "review":
            # the toolless relay has no recon block at all
            assert "RECON TOOL" not in prompt
            assert "RECON SCRIPT" not in prompt
        else:
            assert "RECON SCRIPT" in prompt


# ---------------------------------------------------------------------------
# the read-only arm (no bash)
# ---------------------------------------------------------------------------


def test_apply_arm_read_only_composes_toolset():
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_READONLY)
    assert cfg.arm == ARM_READONLY
    assert cfg.tools.recon.enabled is True
    for phase_id in ("plan", "work"):
        assert _eff(cfg, phase_id) == ["read", "write", "edit", "recon"]
        names = [t.name for t in get_tools(cfg, _eff(cfg, phase_id))]
        assert names == ["read", "write", "edit", "recon"]
        assert "bash" not in names
    # the toolless relay stays toolless; disabled phases are untouched
    assert _eff(cfg, "review") == []
    assert _eff(cfg, "emergency") == BASE_EMERGENCY
    assert _disabled_snapshot(cfg) == disabled_before


def test_env_arm_read_only_prompt_uses_tool_variant(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_READONLY)
    cfg = load_config()
    assert cfg.arm == ARM_READONLY
    for phase_id in PHASES:
        prompt = _system_prompt(cfg, get_phase(phase_id), TASK)
        if phase_id == "review":
            # the toolless relay renders no recon block at all
            assert "RECON TOOL" not in prompt
            assert "RECON SCRIPT" not in prompt
            continue
        if phase_id in ("plan", "work"):
            # the recon block is the tool variant in this arm (issue #109)
            assert "RECON TOOL" in prompt
            assert "RECON SCRIPT" not in prompt
            assert "python3 tools/recon.py" not in prompt
