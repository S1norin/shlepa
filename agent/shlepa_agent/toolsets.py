"""Named toolset arms on top of the modular tool system.

An arm is a stable name for a tool-combination config mutation (the A/B
design in research/notes/toolsets-modular.md). The run loop selects one
arm per run: the CLI passes ``AGENT_TOOLSET`` into the container and
tags the MLflow run with the same string, so runs are filterable by arm.

Arms (the current set; the registry grows as new tool families land):

The 2026-09-07 slim-down (batch ``388fde``: the orientation bundle was
never adopted — code_search 0/649 calls; the extra tool list bloated every
request) left ``recon`` as the ONLY custom tool in the baseline. The
research tool families live on as dev arms below.

- ``baseline``: the current default tool policy — plan gets read + recon
  (no bash, no writes), work gets the standard set
  (read/write/edit/bash) + recon, review (commit) is toolless. No config
  mutation: the packaged config.toml IS the baseline.
- ``+smart-grep``: baseline + the code_search/file_outline pair with the
  engine pinned to ripgrep (the rg engine; the "smart grep" primitive
  from the code-search plan).
- ``+sifs``: baseline + the code_search/file_outline pair over the
  bundled SIFS binary (BM25 offline; the [code_search] engine default).
- ``+forensics``: baseline + the log_triage tool (deterministic read-only
  triage of log/evidence files; research/notes/readonly-tools.md option
  A).
- ``+recon``: baseline + the recon tool (deterministic read-only
  attack-surface recon; the prompt's recon block switches from the script
  to the tool variant, arm-gated in ``runner._system_prompt``; see
  research/notes/recon-tool-conversion.md). The baseline ships recon in
  plan/work, so the arm mutation dedupes to a no-op.
- ``read-only``: read/write/edit + the recon tool, NO bash — the
  experiment arm proving recon is usable by a read-only agent (no code
  execution channel; deliverable writing stays possible).

The legacy dev switch ``AGENT_CODE_SEARCH`` (rg | sifs) still works when
``AGENT_TOOLSET`` is unset (it re-adds the code_search/file_outline pair
with the given engine — the slim baseline no longer ships them); when
both are set, ``AGENT_TOOLSET`` wins (``baseline`` is a no-op — the
packaged config already carries the baseline tool policy). An invalid
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
ARM_RECON = "+recon"
ARM_READONLY = "read-only"

#: Every known arm, in display order.
KNOWN_ARMS: tuple[str, ...] = (
    ARM_BASELINE,
    ARM_SMART_GREP,
    ARM_SIFS,
    ARM_FORENSICS,
    ARM_RECON,
    ARM_READONLY,
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

    ``baseline`` records the arm and mutates nothing (the packaged
    config.toml already carries the baseline tool policy: recon in
    plan/work, toolless review). Search arms re-add the
    code_search/file_outline pair on the pinned engine (rg | sifs) —
    the slim baseline does not ship them, so the mutation enables both
    tools and appends them to the active phases (see
    :func:`shlepa_agent.config._enable_search_tools`).
    """
    from shlepa_agent.config import (
        _apply_read_only_arm,
        _enable_forensics_tools,
        _enable_recon_tools,
        _enable_search_tools,
    )

    cfg.arm = arm
    engine = _ARM_ENGINE.get(arm)
    if engine is not None:
        _enable_search_tools(cfg, engine)
    elif arm == ARM_FORENSICS:
        _enable_forensics_tools(cfg)
    elif arm == ARM_RECON:
        _enable_recon_tools(cfg)
    elif arm == ARM_READONLY:
        _apply_read_only_arm(cfg)
