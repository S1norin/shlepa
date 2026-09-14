"""Named toolset arms on top of the modular tool system.

An arm is a stable name for a tool-combination config mutation (the A/B
design in research/notes/toolsets-modular.md). The run loop selects one
arm per run: the CLI passes ``AGENT_TOOLSET`` into the container and
tags the MLflow run with the same string, so runs are filterable by arm.

Arms (the current set; the registry grows as new tool families land):

The 2026-09-07 slim-down (batch ``388fde``: the orientation bundle was
never adopted — code_search 0/649 calls; the extra tool list bloated every
request) left ``recon`` as the ONLY custom tool in the baseline. The 2026-09-14
cut removed the dev-arm tool families (search/code_search/file_outline/
log_triage) entirely; the surviving arms only rearrange baseline tools.

- ``baseline``: the current default tool policy — plan gets read + recon
  (no bash, no writes), work gets the standard set
  (read/write/edit/bash) + recon, review (commit) is toolless. No config
  mutation: the packaged config.toml IS the baseline.
- ``+recon``: baseline + the recon tool (deterministic read-only
  attack-surface recon; the prompt's recon block switches from the script
  to the tool variant, arm-gated in ``runner._system_prompt``; see
  research/notes/recon-tool-conversion.md). The baseline ships recon in
  plan/work, so the arm mutation dedupes to a no-op.
- ``read-only``: read/write/edit + the recon tool, NO bash — the
  experiment arm proving recon is usable by a read-only agent (no code
  execution channel; deliverable writing stays possible).

An invalid ``AGENT_TOOLSET`` value is ignored (the config stays at the
baseline) — arm selection must never crash the run.
"""

from __future__ import annotations

from shlepa_agent.config import AgentConfig

#: Stable arm names (also the MLflow ``toolset`` tag values).
ARM_BASELINE = "baseline"
ARM_RECON = "+recon"
ARM_READONLY = "read-only"

#: Every known arm, in display order.
KNOWN_ARMS: tuple[str, ...] = (
    ARM_BASELINE,
    ARM_RECON,
    ARM_READONLY,
)


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
    plan/work, toolless review). ``+recon`` enables the recon tool and
    appends it to the active phases (dedupes to a no-op on the packaged
    config); ``read-only`` replaces the active phases' tool lists with
    read/write/edit + recon.
    """
    from shlepa_agent.config import (
        _apply_read_only_arm,
        _enable_recon_tools,
    )

    cfg.arm = arm
    if arm == ARM_RECON:
        _enable_recon_tools(cfg)
    elif arm == ARM_READONLY:
        _apply_read_only_arm(cfg)
