"""Tests for named toolset arms (AGENT_TOOLSET, agent/shlepa_agent/toolsets.py).

The packaged config.toml IS the baseline: recon + code_search + file_outline
on (rg engine), with the per-phase tool matrix (plan: read + recon + search,
no bash; work: full set + recon + search; review: toolless; emergency:
legacy four). The arms are switches on top of it:
+smart-grep (pin rg), +sifs (pin sifs), +forensics (log_triage),
+mitre-kb (mitre_kb), +recon (no-op, recon is baseline now), read-only
(read/write/edit + recon, no bash). AGENT_TOOLSET is the sole driver of the
code-search toolset when set (it wins over the legacy AGENT_CODE_SEARCH
switch); an invalid value is ignored, never a crash.
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

PHASES = ("plan", "work", "commit", "emergency")
TASK = "TASK"

#: The baseline tool matrix (config.toml). Arm mutations are diffs against
#: this: search arms only pin the engine (tools already wired), forensics /
#: mitre-kb append their tool to every TOOLED phase, and the toolless review
#: stays toolless under every arm.
BASE_PLAN = ["read", "recon", "code_search", "file_outline"]
BASE_WORK = [
    "read",
    "write",
    "edit",
    "bash",
    "recon",
    "code_search",
    "file_outline",
]
BASE_COMMIT = []
BASE_EMERGENCY = ["read", "write", "edit", "bash"]
BASE_MATRIX = {
    "plan": BASE_PLAN,
    "work": BASE_WORK,
    "commit": BASE_COMMIT,
    "emergency": BASE_EMERGENCY,
}
def _clear(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)


def _with_tools(phase_id: str, tools: tuple[str, ...]) -> list[str]:
    """Baseline phase list after an arm appends ``tools``.

    Mirrors ``_append_to_phases``: every TOOLED phase gets the arm tools
    (deduped, order preserved); a toolless phase stays toolless.
    """
    base = list(BASE_MATRIX[phase_id])
    if not base:
        return base
    for tool in tools:
        if tool not in base:
            base.append(tool)
    return base


#: Baseline matrix after a search arm / the legacy switch: the search tools
#: are already wired in plan/work (deduped) but land in the legacy emergency.
SEARCH_MATRIX = {
    p: _with_tools(p, ("code_search", "file_outline")) for p in PHASES
}

#: Baseline matrix after the +recon arm: recon lands in the legacy emergency
#: only (plan/work already ship it).
RECON_MATRIX = {p: _with_tools(p, ("recon",)) for p in PHASES}


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
    snapshot = {p: list(cfg.phases[p].tools) for p in PHASES}
    snapshot_engine = cfg.code_search.engine
    apply_arm(cfg, ARM_BASELINE)
    assert cfg.arm == ARM_BASELINE
    # the packaged config.toml IS the baseline: recon + search on, rg engine
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.recon.enabled is True
    assert cfg.code_search.engine == snapshot_engine
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == snapshot[phase_id]


@pytest.mark.parametrize(
    ("arm", "engine"),
    [(ARM_SMART_GREP, "rg"), (ARM_SIFS, "sifs")],
)
def test_apply_arm_search_arms_pin_engine(monkeypatch, arm, engine):
    _clear(monkeypatch)
    cfg = load_config()
    apply_arm(cfg, arm)
    assert cfg.arm == arm
    # the baseline already wires the tools: the arm only pins the engine
    assert cfg.code_search.engine == engine
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    # the baseline already wires the tools in plan/work (deduped); they land
    # in the legacy emergency, and the toolless review stays toolless.
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == SEARCH_MATRIX[phase_id]


def test_apply_arm_forensics_enables_tool():
    cfg = load_config()
    apply_arm(cfg, ARM_FORENSICS)
    assert cfg.arm == ARM_FORENSICS
    # the search family stays on (different family)
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.log_triage.enabled is True
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == _with_tools(phase_id, ("log_triage",))


def test_env_arm_forensics_enables_tool_and_prompt(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_FORENSICS)
    cfg = load_config()
    assert cfg.arm == ARM_FORENSICS
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == _with_tools(phase_id, ("log_triage",))
        prompt = _system_prompt(cfg, phase, TASK)
        if phase_id == "commit":
            # the toolless review is never augmented
            assert "log_triage: deterministic read-only triage" not in prompt
        else:
            assert "log_triage: deterministic read-only triage" in prompt


# ---------------------------------------------------------------------------
# the +mitre-kb arm (mitre_kb)
# ---------------------------------------------------------------------------


def test_apply_arm_mitre_kb_enables_tool():
    cfg = load_config()
    apply_arm(cfg, ARM_MITRE_KB)
    assert cfg.arm == ARM_MITRE_KB
    # the search family stays on (different family)
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is True
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == _with_tools(phase_id, ("mitre_kb",))


def test_env_arm_mitre_kb_enables_tool_and_prompt(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_MITRE_KB)
    cfg = load_config()
    assert cfg.arm == ARM_MITRE_KB
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == _with_tools(phase_id, ("mitre_kb",))
        prompt = _system_prompt(cfg, phase, TASK)
        if phase_id == "commit":
            # the toolless review: no tool note, no arm-gated KB prefix
            assert "mitre_kb: search the pinned MITRE ATT&CK" not in prompt
            assert "MITRE ATT&CK knowledge base" not in prompt
        else:
            assert "mitre_kb: search the pinned MITRE ATT&CK" in prompt
            # the arm-gated stable prefix: index + alias map
            assert "MITRE ATT&CK knowledge base" in prompt
            assert "T1003.003 NTDS" in prompt
            assert "T1562.001 -> T1685" in prompt


# ---------------------------------------------------------------------------
# env wiring (AGENT_TOOLSET)
# ---------------------------------------------------------------------------


def test_env_arm_baseline_is_the_packaged_config(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_BASELINE)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "sifs")
    cfg = load_config()
    # AGENT_TOOLSET wins over the legacy switch; baseline is a no-op, so
    # the packaged config (rg engine, search on) stays
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.log_triage.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_MATRIX[phase_id]


def test_env_arm_invalid_is_ignored_never_crashes(monkeypatch):
    _clear(monkeypatch)
    for value in ("banana", "+sifs-hybrid", "smart-grep"):
        monkeypatch.setenv("AGENT_TOOLSET", value)
        cfg = load_config()
        # an unknown arm is ignored: the packaged baseline stays
        assert cfg.arm == ARM_BASELINE, value
        assert cfg.code_search.engine == "rg", value
        assert cfg.tools.code_search.enabled is True, value
        assert cfg.tools.file_outline.enabled is True, value
        assert cfg.tools.log_triage.enabled is False, value
        assert cfg.tools.mitre_kb.enabled is False, value
        assert cfg.tools.recon.enabled is True, value


def test_env_unset_defaults_to_baseline(monkeypatch):
    _clear(monkeypatch)
    cfg = load_config()
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "rg"
    # baseline ships recon + search; forensics + KB stay off
    assert cfg.tools.recon.enabled is True
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == BASE_MATRIX[phase_id]


def test_legacy_code_search_switch_still_works_without_toolset(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "sifs")
    cfg = load_config()
    # the legacy switch is not an arm: cfg.arm stays baseline, engine follows
    assert cfg.arm == ARM_BASELINE
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is True
    # the switch enables the family: deduped in plan/work, lands in emergency
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == SEARCH_MATRIX[phase_id]


# ---------------------------------------------------------------------------
# the +recon arm (recon is baseline now: the arm is a no-op)
# ---------------------------------------------------------------------------


def test_apply_arm_recon_is_a_noop():
    cfg = load_config()
    apply_arm(cfg, ARM_RECON)
    assert cfg.arm == ARM_RECON
    # the search family is on (baseline), the other families stay off
    assert cfg.code_search.engine == "rg"
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    assert cfg.tools.log_triage.enabled is False
    assert cfg.tools.mitre_kb.enabled is False
    assert cfg.tools.recon.enabled is True
    # recon is already wired in plan/work (deduped); it lands in the legacy
    # emergency, the toolless review stays toolless
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == RECON_MATRIX[phase_id]


def test_env_arm_recon_uses_tool_prompt_variant(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_RECON)
    cfg = load_config()
    assert cfg.arm == ARM_RECON
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == RECON_MATRIX[phase_id]
        prompt = _system_prompt(cfg, phase, TASK)
        # every tooled phase renders the tool variant in place of the script
        if phase_id in ("plan", "work", "emergency"):
            assert "RECON TOOL" in prompt
            assert 'mode "web"' in prompt
            assert "RECON SCRIPT" not in prompt
            assert "python3 tools/recon.py" not in prompt
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
        elif phase_id == "commit":
            # the toolless review has no recon block at all
            assert "RECON TOOL" not in prompt
            assert "RECON SCRIPT" not in prompt
        else:
            assert "RECON SCRIPT" in prompt


# ---------------------------------------------------------------------------
# the read-only arm (no bash)
# ---------------------------------------------------------------------------


def test_apply_arm_read_only_composes_toolset():
    cfg = load_config()
    apply_arm(cfg, ARM_READONLY)
    assert cfg.arm == ARM_READONLY
    assert cfg.tools.recon.enabled is True
    for phase_id in PHASES:
        if phase_id == "commit":
            # the toolless review stays toolless under every arm
            assert list(cfg.phases[phase_id].tools) == []
            continue
        assert list(cfg.phases[phase_id].tools) == [
            "read",
            "write",
            "edit",
            "recon",
        ]
        names = [t.name for t in get_tools(cfg, get_phase(phase_id).tools(cfg))]
        assert names == ["read", "write", "edit", "recon"]
        assert "bash" not in names


def test_env_arm_read_only_prompt_uses_tool_variant(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("AGENT_TOOLSET", ARM_READONLY)
    cfg = load_config()
    assert cfg.arm == ARM_READONLY
    for phase_id in PHASES:
        if phase_id == "commit":
            # the toolless review renders no recon block at all
            prompt = _system_prompt(cfg, get_phase(phase_id), TASK)
            assert "RECON TOOL" not in prompt
            assert "RECON SCRIPT" not in prompt
            continue
        prompt = _system_prompt(cfg, get_phase(phase_id), TASK)
        # the recon block is the tool variant in this arm (issue #109)
        assert "RECON TOOL" in prompt
        assert "RECON SCRIPT" not in prompt
        assert "python3 tools/recon.py" not in prompt
