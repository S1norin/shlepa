"""Named toolset arms on top of the modular tool system.

An arm is a stable name for a tool-combination config mutation (the A/B
design in research/notes/toolsets-modular.md). The run loop selects one
arm per run: the CLI passes ``AGENT_TOOLSET`` into the container and
tags the MLflow run with the same string, so runs are filterable by arm.

Arms (the current set; the registry grows as new tool families land):

- ``baseline``: the v5 default tool set (read/write/edit/bash). No
  config mutation — the agent stays byte-identical to the pre-arm
  baseline.
- ``+smart-grep``: baseline + code_search/file_outline over ripgrep
  (the rg engine; the "smart grep" primitive from the code-search plan).
- ``+sifs``: baseline + code_search/file_outline over the bundled SIFS
  binary (BM25 offline).
- ``+forensics``: baseline + the log_triage tool (deterministic read-only
  triage of log/evidence files; research/notes/readonly-tools.md option A).

The legacy dev switch ``AGENT_CODE_SEARCH`` (rg | sifs) still works when
``AGENT_TOOLSET`` is unset; when both are set, ``AGENT_TOOLSET`` wins
(including ``baseline``, which forces the search tools off). An invalid
``AGENT_TOOLSET`` value is ignored (the config stays at the baseline) —
arm selection must never crash the run.
"""

from __future__ import annotations

from shlepa_agent.config import AgentConfig

#: Stable arm names (also the MLflow ``toolset`` tag values).
ARM_BASELINE = "baseline"
ARM_SMART_GREP = "+smart-grep"
ARM_SIFS = "+sifs"
ARM_FORENSICS = "+forensics"

#: Every known arm, in display order.
KNOWN_ARMS: tuple[str, ...] = (
    ARM_BASELINE,
    ARM_SMART_GREP,
    ARM_SIFS,
    ARM_FORENSICS,
)

#: Search arms -> the engine their code_search toolset uses.
_ARM_ENGINE: dict[str, str] = {
    ARM_SMART_GREP: "rg",
    ARM_SIFS: "sifs",
}


def resolve_arm(spec: str) -> str:
    """Normalize an arm spec to a known arm name.

    Raises:
        ValueError: unknown arm (the CLI turns this into an exit code;
            the config layer ignores invalid env values instead).
    """
    arm = spec.strip()
    if arm not in KNOWN_ARMS:
        raise ValueError(
            f"unknown toolset arm: {spec!r} (known: {', '.join(KNOWN_ARMS)})"
        )
    return arm


def apply_arm(cfg: AgentConfig, arm: str) -> None:
    """Apply one arm's config mutation to a loaded config.

    ``baseline`` records the arm and mutates nothing. Search arms enable
    the code_search/file_outline tools and append them to every phase's
    tool list (the same mutation the legacy AGENT_CODE_SEARCH switch
    performs; see :func:`shlepa_agent.config._enable_search_tools`).
    """
    from shlepa_agent.config import _enable_forensics_tools, _enable_search_tools

    cfg.arm = arm
    engine = _ARM_ENGINE.get(arm)
    if engine is not None:
        _enable_search_tools(cfg, engine)
    elif arm == ARM_FORENSICS:
        _enable_forensics_tools(cfg)
