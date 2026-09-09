"""Tests for named toolset arms (AGENT_TOOLSET, agent/shlepa_agent/toolsets.py).

The packaged config.toml IS the baseline (2026-09-07 slim-down): recon is
the ONLY custom tool (plan read+recon, work standard set + recon), toolless
review relay, disabled phases (commit/repair/salvage/emergency) never
routed. The research tool families live on as dev arms: +smart-grep /
+sifs re-add code_search+file_outline (rg | sifs engine), +forensics adds
log_triage, +mitre-kb adds mitre_kb, +recon is a no-op (recon is
baseline), read-only (read/write/edit + recon, no bash). AGENT_TOOLSET is
the sole driver of the arm mutation when set (it wins over the legacy
AGENT_CODE_SEARCH switch); an invalid value is ignored, never a crash.

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
    ARM_FORENSICS,
    ARM_MITRE_KB,
    ARM_READONLY,
    ARM_RECON,
    ARM_SIFS,
    ARM_SMART_GREP,
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
#: against this: the search arms re-add code_search+file_outline (appended),
#: +forensics/+mitre-kb append their tool to every active TOOLED phase,
#: and the toolless review stays toolless under every arm.
BASE_PLAN = ["read", "recon"]
BASE_WORK = ["read", "write", "edit", "bash", "recon"]
BASE_SEARCH = ["code_search", "file_outline"]
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
    "commit": ["read", "search"],
    "repair": ["read", "search", "edit"],
    "salvage": ["write"],
}


def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)


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
    snapshot = {p: _eff(cfg, p) for p in PHASES}
    snapshot_engine = cfg.code_search.engine
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_BASELINE)
    assert cfg.arm == ARM_BASELINE
    # the packaged config.toml IS the slim baseline: recon on, the research
    # tool families off, sifs engine (for the arms that re-add the pair)
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.recon.enabled is True
    assert cfg.tools.log_triage.enabled is False
    assert cfg.code_search.engine == snapshot_engine
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == snapshot[phase_id]
    assert _disabled_snapshot(cfg) == disabled_before


@pytest.mark.parametrize(
    ("arm", "engine"),
    [(ARM_SMART_GREP, "rg"), (ARM_SIFS, "sifs")],
)
def test_apply_arm_search_arms_readd_pair_with_pinned_engine(
    monkeypatch, arm, engine
):
    _clear(monkeypatch)
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, arm)
    assert cfg.arm == arm
    # the slim baseline does not ship the pair: the arm enables both tools
    # on the pinned engine and appends them to the active TOOLED phases
    # (disabled phases are never augmented)
    assert cfg.code_search.engine == engine
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert _eff(cfg, "plan") == BASE_PLAN + BASE_SEARCH
    assert _eff(cfg, "work") == BASE_WORK + BASE_SEARCH
    assert _eff(cfg, "review") == BASE_REVIEW
    assert _eff(cfg, "emergency") == BASE_EMERGENCY
    assert _disabled_snapshot(cfg) == disabled_before


def test_apply_arm_forensics_enables_tool():
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_FORENSICS)
    assert cfg.arm == ARM_FORENSICS
    # the search family stays off (different family)
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is True
    # log_triage is appended to the active TOOLED phases
    assert _eff(cfg, "plan") == BASE_PLAN + ["log_triage"]
    assert _eff(cfg, "work") == BASE_WORK + ["log_triage"]
    assert _eff(cfg, "review") == BASE_REVIEW
    assert _eff(cfg, "emergency") == BASE_EMERGENCY
    assert _disabled_snapshot(cfg) == disabled_before


def test_env_arm_forensics_enables_tool_and_prompt(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_FORENSICS)
    cfg = load_config()
    assert cfg.arm == ARM_FORENSICS
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, _eff(cfg, phase_id))]
        if phase_id == "plan":
            assert names == BASE_PLAN + ["log_triage"]
        elif phase_id == "work":
            assert names == BASE_WORK + ["log_triage"]
        else:
            assert names == BASE_MATRIX[phase_id]
        prompt = _system_prompt(cfg, phase, TASK)
        if phase_id in ("plan", "work"):
            # the arm re-adds the tool: its note renders in the active phases
            assert "log_triage: deterministic read-only triage" in prompt
        else:
            # the toolless relay and the disabled emergency never carry it
            assert "log_triage: deterministic read-only triage" not in prompt


# ---------------------------------------------------------------------------
# the +mitre-kb arm (mitre_kb)
# ---------------------------------------------------------------------------


def test_apply_arm_mitre_kb_enables_tool():
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_MITRE_KB)
    assert cfg.arm == ARM_MITRE_KB
    # the search family stays off (different family)
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.mitre_kb.enabled is True
    # mitre_kb lands in every active TOOLED phase; the toolless review and
    # the disabled phases are never augmented
    assert _eff(cfg, "plan") == BASE_PLAN + ["mitre_kb"]
    assert _eff(cfg, "work") == BASE_WORK + ["mitre_kb"]
    assert _eff(cfg, "review") == []
    assert _eff(cfg, "emergency") == BASE_EMERGENCY
    assert _disabled_snapshot(cfg) == disabled_before


def test_env_arm_mitre_kb_enables_tool_and_prompt(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_MITRE_KB)
    cfg = load_config()
    assert cfg.arm == ARM_MITRE_KB
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, _eff(cfg, phase_id))]
        if phase_id == "review":
            # the toolless relay: no tool, no note, no arm-gated KB prefix
            assert names == []
            assert "mitre_kb: search the pinned MITRE ATT&CK" not in names
            prompt = _system_prompt(cfg, phase, TASK)
            assert "mitre_kb" not in prompt
            assert "MITRE ATT&CK knowledge base" not in prompt
            continue
        if phase_id in ("plan", "work"):
            base = BASE_PLAN if phase_id == "plan" else BASE_WORK
            assert names == base + ["mitre_kb"]
            prompt = _system_prompt(cfg, phase, TASK)
            assert "mitre_kb: search the pinned MITRE ATT&CK" in prompt
            # the arm-gated stable prefix: index + alias map
            assert "MITRE ATT&CK knowledge base" in prompt
            assert "T1003.003 NTDS" in prompt
            assert "T1562.001 -> T1685" in prompt
        else:
            # the disabled emergency keeps its baseline list (arms never
            # augment disabled phases) and gets no KB prefix
            assert names == BASE_EMERGENCY
            assert "MITRE ATT&CK knowledge base" not in _system_prompt(
                cfg, phase, TASK
            )


# ---------------------------------------------------------------------------
# env wiring (AGENT_TOOLSET)
# ---------------------------------------------------------------------------


def test_env_arm_baseline_is_the_packaged_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_BASELINE)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg = load_config()
    # AGENT_TOOLSET wins over the legacy switch; baseline is a no-op, so
    # the packaged slim config (sifs engine, slim matrix) stays
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is False
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id]


def test_env_arm_invalid_is_ignored_never_crashes(monkeypatch):
    _clear(monkeypatch)
    for value in ("banana", "+sifs-hybrid", "smart-grep"):
        monkeypatch.setenv("AGENT_TOOLSET", value)
        cfg = load_config()
        # an unknown arm is ignored: the packaged slim baseline stays
        assert cfg.arm == ARM_BASELINE, value
        assert cfg.code_search.engine == "sifs", value
        assert cfg.tools.code_search.enabled is False, value
        assert cfg.tools.file_outline.enabled is False, value
        assert cfg.tools.log_triage.enabled is False, value
        assert cfg.tools.mitre_kb.enabled is False, value
        assert cfg.tools.recon.enabled is True, value
        for phase_id in PHASES:
            assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id], value


def test_env_unset_defaults_to_baseline(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "sifs"
    # the slim baseline ships recon only; the research families stay off
    assert cfg.tools.recon.enabled is True
    assert cfg.tools.search.enabled is False
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is False
    for phase_id in PHASES:
        assert _eff(cfg, phase_id) == BASE_MATRIX[phase_id]


def test_legacy_code_search_switch_readds_pair_without_toolset(monkeypatch):
    _clear(monkeypatch)
    for value, engine in (("rg", "rg"), ("sifs", "sifs")):
        monkeypatch.setenv("AGENT_CODE_SEARCH", value)
        cfg = load_config()
        # the legacy switch is not an arm: cfg.arm stays baseline, the
        # engine follows, and the slim baseline's missing pair is re-added
        # (the pre-slim-dev behavior of "just set the engine")
        assert cfg.arm == ARM_BASELINE, value
        assert cfg.code_search.engine == engine, value
        assert cfg.tools.code_search.enabled is True, value
        assert _eff(cfg, "plan") == BASE_PLAN + BASE_SEARCH, value
        assert _eff(cfg, "work") == BASE_WORK + BASE_SEARCH, value
        assert _eff(cfg, "review") == BASE_REVIEW, value
        assert _eff(cfg, "emergency") == BASE_EMERGENCY, value


# ---------------------------------------------------------------------------
# the +recon arm (recon is baseline now: the arm is a no-op)
# ---------------------------------------------------------------------------


def test_apply_arm_recon_is_a_noop():
    cfg = load_config()
    disabled_before = _disabled_snapshot(cfg)
    apply_arm(cfg, ARM_RECON)
    assert cfg.arm == ARM_RECON
    # the research families stay off, the KB stays off
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is False
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
