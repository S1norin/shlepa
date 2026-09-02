"""Tests for named toolset arms (AGENT_TOOLSET, agent/shlepa_agent/toolsets.py).

Arms: baseline (no-op, byte-identical default), +smart-grep (rg engine),
+sifs (SIFS engine). AGENT_TOOLSET is the sole driver of the code-search
toolset when set (it wins over the legacy AGENT_CODE_SEARCH switch); an
invalid value is ignored, never a crash.
"""

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.runner import _system_prompt
from shlepa_agent.tools import get_tools
from shlepa_agent.toolsets import (
    ARM_BASELINE,
    ARM_FORENSICS,
    ARM_SIFS,
    ARM_SMART_GREP,
    KNOWN_ARMS,
    apply_arm,
    resolve_arm,
)

PHASES = ("plan", "work", "commit", "emergency")
TASK = "TASK"
BASE_TOOLS = ["read", "write", "edit", "bash"]


def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)


# ---------------------------------------------------------------------------
# resolve_arm
# ---------------------------------------------------------------------------


def test_resolve_arm_returns_known_names():
    for arm in KNOWN_ARMS:
        assert resolve_arm(arm) == arm


def test_resolve_arm_strips_whitespace():
    assert resolve_arm("  +sifs  ") == ARM_SIFS
    assert resolve_arm("\nbaseline\n") == ARM_BASELINE


def test_resolve_arm_unknown_raises():
    for value in ("", "banana", "+sifs-hybrid", "smart-grep", "BASELINE"):
        with pytest.raises(ValueError, match="unknown toolset arm"):
            resolve_arm(value)


# ---------------------------------------------------------------------------
# apply_arm (direct, no env)
# ---------------------------------------------------------------------------


def test_apply_arm_baseline_is_a_noop():
    cfg = load_config()
    apply_arm(cfg, ARM_BASELINE)
    assert cfg.arm == ARM_BASELINE
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_TOOLS


@pytest.mark.parametrize(
    ("arm", "engine"),
    [(ARM_SMART_GREP, "rg"), (ARM_SIFS, "sifs")],
)
def test_apply_arm_search_arms_enable_tools(monkeypatch, arm, engine):
    _clear(monkeypatch)
    cfg = load_config()
    apply_arm(cfg, arm)
    assert cfg.arm == arm
    assert cfg.code_search.engine == engine
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_TOOLS + [
            "code_search",
            "file_outline",
        ]


# ---------------------------------------------------------------------------
# env wiring (AGENT_TOOLSET)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arm", "engine"),
    [(ARM_SMART_GREP, "rg"), (ARM_SIFS, "sifs")],
)
def test_env_arm_enables_tools_and_engine(monkeypatch, arm, engine):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", arm)
    cfg = load_config()
    assert cfg.arm == arm
    assert cfg.code_search.engine == engine
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == BASE_TOOLS + ["code_search", "file_outline"]
        prompt = _system_prompt(cfg, phase, TASK)
        assert "code_search: search the codebase" in prompt
        assert "file_outline: list def/class/func symbols" in prompt


# ---------------------------------------------------------------------------
# the +forensics arm (log_triage)
# ---------------------------------------------------------------------------


def test_apply_arm_forensics_enables_log_triage():
    cfg = load_config()
    apply_arm(cfg, ARM_FORENSICS)
    assert cfg.arm == ARM_FORENSICS
    # the search tools stay off (different family)
    assert cfg.code_search.engine == "auto"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is True
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_TOOLS + ["log_triage"]


def test_env_arm_forensics_enables_tool_and_prompt(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_FORENSICS)
    cfg = load_config()
    assert cfg.arm == ARM_FORENSICS
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == BASE_TOOLS + ["log_triage"]
        prompt = _system_prompt(cfg, phase, TASK)
        assert "log_triage: deterministic read-only triage" in prompt


def test_env_arm_baseline_forces_tools_off_over_legacy_switch(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_BASELINE)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "sifs")
    cfg = load_config()
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "auto"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_TOOLS


def test_env_arm_invalid_is_ignored_never_crashes(monkeypatch):
    _clear(monkeypatch)
    for value in ("banana", "+sifs-hybrid", "smart-grep"):
        monkeypatch.setenv("AGENT_TOOLSET", value)
        cfg = load_config()
        assert cfg.arm == ARM_BASELINE, value
        assert cfg.tools.code_search.enabled is False, value
        assert cfg.tools.file_outline.enabled is False, value
        assert cfg.tools.log_triage.enabled is False, value
        assert cfg.code_search.engine == "auto", value


def test_env_unset_defaults_to_baseline(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "auto"
    # default agent is byte-identical to baseline: forensics off too
    assert cfg.tools.log_triage.enabled is False


def test_legacy_code_search_switch_still_works_without_toolset(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg = load_config()
    # the legacy switch is not an arm: cfg.arm stays baseline
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
