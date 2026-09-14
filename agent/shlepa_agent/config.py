"""Typed agent configuration for the v2 architecture.

Single source of tuning values: ``shlepa_agent/config.toml`` (shipped inside
the package, carried by the submission zip). Environment variables override
individual keys (``SHLEPA_*`` names; the legacy ``AGENT_*`` names were
dropped with the v2 architecture — see ``docs/agent-config.md`` for the
mapping; ``AGENT_TOOLSET`` is the deliberate
exception, wired in ``_apply_toolset_env``). Invalid env values are
ignored, matching the old ``_env_*`` helpers.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class AgentSection(BaseModel):
    """Run-level settings: pipeline entry, cycle count, step guard.

    v6-rewrite: HARD cycle regime — the run executes exactly ``max_cycles``
    plan -> work cycles (plus a review relay after every cycle except the
    last, env: SHLEPA_MAX_CYCLES, default 2). There is NO task time limit T;
    the container is killed at the task's own limit.
    """

    #: Entry phase. Empty = "plan".
    entry: str = ""
    #: Name of the emergency phase (disabled, kept for compatibility).
    emergency: str = "emergency"
    # Total phase-run guard (dev knob). 0 = off.
    max_steps: int = Field(default=0, ge=0)
    #: Hard cycle count (v6-rewrite, env: SHLEPA_MAX_CYCLES). The run
    #: executes exactly this many plan -> work cycles; the review relay
    #: runs after every cycle except the last.
    max_cycles: int = Field(default=2, ge=1)
    #: Sampling temperature; sent to the endpoint only when ``send_temp``
    #: is enabled (default: the endpoint decides).
    temp: float = 0.6
    #: Send ``temp`` in model settings (env: SHLEPA_SEND_TEMP, 1/0).
    send_temp: bool = False


class BudgetConfig(BaseModel):
    """Per-request caps for the fixed v5 regime.

    The phase caps are fixed constants (``budget.py``); there is NO task
    time limit T, NO global hard stop and NO request-start gate. There is
    NO global token budget and NO request-count limit (token usage is
    logged for analysis only).
    """

    # Hard per-request output cap; without it a single request can loop for
    # tens of thousands of tokens and eat the whole trial.
    max_tokens: int = 16_384
    # Per-request open timeout (up to the first bytes).
    request_timeout: float = 180.0
    # w3-5: after this many CONSECUTIVE terminal endpoint failures
    # (429/402/5xx) the runner finalizes the run: no further LLM
    # requests, the best deliverable is persisted, exit stays 0.
    endpoint_fail_limit: int = 3


class ToolConfig(BaseModel):
    """Per-tool settings. Fields are used where relevant:

    - ``timeout``: bash default per-call timeout (seconds)
    - ``max_timeout``: bash hard cap for the per-call timeout (seconds)
    - ``max_limit``: read max lines per call
    - ``max_output``: hard char cap on the tool result (read: 4000, bash: 16000)
    - ``max_file_mb``: file size cap for read/edit (default 100 MB; larger
      files are rejected with a bash hint instead of being loaded)
    """

    enabled: bool = True
    timeout: float | None = None
    max_timeout: float | None = None
    max_output: int | None = None
    max_limit: int | None = None
    max_file_mb: float | None = None


class ToolsConfig(BaseModel):
    bash: ToolConfig = ToolConfig(enabled=True, timeout=30.0, max_timeout=30.0, max_output=16000)
    read: ToolConfig = ToolConfig(enabled=True, max_limit=100, max_output=4000)
    write: ToolConfig = ToolConfig()
    edit: ToolConfig = ToolConfig()
    #: Deterministic surface map wrapping tools/recon.py (read-only).
    recon: ToolConfig = ToolConfig(enabled=True, max_output=8192)

    def get(self, name: str) -> ToolConfig:
        try:
            return getattr(self, name)
        except AttributeError:
            raise KeyError(f"unknown tool: {name}") from None


class BlockWrapper(BaseModel):
    """Optional before/after text wrapping one template block."""

    before: str = ""
    after: str = ""


class PhaseConfig(BaseModel):
    """One phase of the pipeline: hard/advisory limits, template overrides.

    - ``time``: explicit hard wall-clock cap for the phase run. ``None``
      (omitted) = the fixed regime constant for the phase (``budget.py``).
    - ``soft_time`` / ``soft_tokens``: advisory only. Rendered into the phase
      prompt and status lines; they never cut the phase.

    The toolset is NOT declared here anymore (v6-rewrite): the single source
    is the ``[tool_policy]`` section. ``tools`` is a legacy fallback for
    dev/test configs that predate the policy section.
    """

    tools: list[str] = Field(default_factory=list)
    requests: int = Field(ge=1)
    time: float | None = Field(default=None, gt=0)
    soft_time: float | None = Field(default=None, gt=0)
    soft_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: str | None = None
    max_retries: int = Field(default=2, ge=0)
    # Per-phase template wrapper overrides: block name -> before/after.
    template: dict[str, BlockWrapper] = Field(default_factory=dict)


class ToolPolicy(BaseModel):
    """Single source of tool availability: the phase x iteration matrix
    (v6-rewrite decision).

    ``phases`` maps a phase id to its tool list; an optional per-iteration
    override key ``"<phase>_c<N>"`` (N >= 1) beats the phase entry for that
    iteration only. ``disabled`` lists phase ids that exist in code and
    config but are never routed to (commit/repair/salvage/emergency: kept
    on disk for a later re-enable).
    """

    phases: dict[str, list[str]] = Field(default_factory=dict)
    disabled: list[str] = Field(default_factory=list)

    def tools_for(
        self, phase_id: str, cycle: int = 1, fallback: list[str] | None = None
    ) -> list[str]:
        """Resolve the tool list for one phase run in iteration ``cycle``.

        Precedence: per-iteration override ``<phase>_c<N>`` -> phase entry ->
        legacy ``[phases.<id>].tools`` fallback (dev/test configs).
        """
        override = self.phases.get(f"{phase_id}_c{max(1, cycle)}")
        if override is not None:
            return list(override)
        entry = self.phases.get(phase_id)
        if entry is not None:
            return list(entry)
        return list(fallback or [])

    def is_disabled(self, phase_id: str) -> bool:
        return phase_id in self.disabled


class TemplateConfig(BaseModel):
    """Common request template: ordered block list + default wrappers.

    Block targets: ``system`` and ``tools`` render into the system message
    (in list order); all other blocks render into the per-phase user message
    (in list order). A block with empty content is dropped together with
    its wrappers.
    """

    blocks: list[str] = Field(min_length=1)
    wrappers: dict[str, BlockWrapper] = Field(default_factory=dict)


class AgentConfig(BaseModel):
    agent: AgentSection = Field(default_factory=AgentSection)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)
    # Resolved toolset arm (see toolsets.py): "baseline" when AGENT_TOOLSET
    # is unset or invalid. Data only — never rendered into the prompt.
    arm: str = "baseline"
    phases: dict[str, PhaseConfig] = Field(min_length=1)
    template: TemplateConfig = Field(
        default_factory=lambda: TemplateConfig(blocks=["system", "tools", "task"])
    )


def _env_bool(raw: str) -> bool:
    """Parse a 1/0 (or true/false/yes/no/on/off) boolean env override."""
    low = raw.strip().lower()
    if low in ("1", "true", "yes", "on"):
        return True
    if low in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"not a bool: {raw!r}")


#: Env-var overrides: name -> (dotted config path, target type).
ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "SHLEPA_TEMP": ("agent.temp", float),
    "SHLEPA_SEND_TEMP": ("agent.send_temp", _env_bool),
    "SHLEPA_MAX_STEPS": ("agent.max_steps", int),
    "SHLEPA_BUDGET_MAX_TOKENS": ("budget.max_tokens", int),
    "SHLEPA_BUDGET_REQUEST_TIMEOUT": ("budget.request_timeout", float),
    "SHLEPA_BASH_TIMEOUT": ("tools.bash.timeout", float),
    "SHLEPA_BASH_MAX_TIMEOUT": ("tools.bash.max_timeout", float),
    "SHLEPA_BASH_MAX_OUTPUT": ("tools.bash.max_output", int),
    "SHLEPA_READ_MAX_LIMIT": ("tools.read.max_limit", int),
    "SHLEPA_READ_MAX_OUTPUT": ("tools.read.max_output", int),
    "SHLEPA_COMMIT_TIME": ("phases.commit.time", float),
    "SHLEPA_COMMIT_REASONING_EFFORT": ("phases.commit.reasoning_effort", str),
    "SHLEPA_PLAN_TIME": ("phases.plan.time", float),
    "SHLEPA_RECON_TIMEOUT": ("tools.recon.timeout", float),
    "SHLEPA_RECON_MAX_OUTPUT": ("tools.recon.max_output", int),
    "SHLEPA_MAX_CYCLES": ("agent.max_cycles", int),
    "SHLEPA_REVIEW_TIME": ("phases.review.time", float),
}


def _apply_env_overrides(cfg: AgentConfig) -> None:
    for env_name, (path, cast) in ENV_OVERRIDES.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        try:
            value: Any = cast(raw)
        except (TypeError, ValueError):
            continue  # invalid override: ignore, keep the file value
        node: Any = cfg
        parts = path.split(".")
        for part in parts[:-1]:
            if isinstance(node, dict):
                node = node[part]
            else:
                node = getattr(node, part)
        last = parts[-1]
        if isinstance(node, dict):
            node[last] = value
        else:
            setattr(node, last, value)


#: The one deliberate AGENT_* env var (the legacy set was dropped in v2):
#: AGENT_TOOLSET, the named-arm selector (see toolsets.py).
TOOLSET_ENV = "AGENT_TOOLSET"


def _append_to_phases(cfg: AgentConfig, names: tuple[str, ...]) -> None:
    """Append tool names to every ACTIVE phase's tool list (deduped).

    Targets the effective source of the phase list: the ``[tool_policy]``
    entry when the phase has one, otherwise the legacy
    ``[phases.<id>].tools`` (dev/test configs without a policy section).
    Phases listed in ``tool_policy.disabled`` are never routed, so arms
    never touch their lists. An EMPTY list is a deliberate toolless phase
    (the v6 review relay) — it is never augmented, so a toolless phase
    stays toolless on every arm.
    """
    for phase_id, phase in cfg.phases.items():
        if cfg.tool_policy.is_disabled(phase_id):
            continue
        entry = cfg.tool_policy.phases.get(phase_id)
        if entry is not None:
            if not entry:
                continue
            for name in names:
                if name not in entry:
                    entry.append(name)
        else:
            if not phase.tools:
                continue
            for name in names:
                if name not in phase.tools:
                    phase.tools.append(name)


def _enable_recon_tools(cfg: AgentConfig) -> None:
    """Enable the recon tool (the +recon arm mutation).

    The v6 baseline already routes recon via [tool_policy]; on the packaged
    config this dedupes to a no-op.
    """
    cfg.tools.recon.enabled = True
    _append_to_phases(cfg, ("recon",))


def _apply_read_only_arm(cfg: AgentConfig) -> None:
    """Read-only arm mutation: read/write/edit + recon, NO bash.

    The experiment arm proving recon is usable by an agent without a
    code-execution channel (deliverable writing stays possible via
    write/edit; 'read-only' = no bash, not a read-only filesystem).
    Replaces the effective tool list of every active TOOLED phase (the
    ``[tool_policy]`` entry when the phase has one, otherwise the legacy
    ``[phases.<id>].tools``); disabled phases are never touched and a
    toolless phase (the review relay) stays toolless under every arm.
    """
    cfg.tools.recon.enabled = True
    for phase_id, phase in cfg.phases.items():
        if cfg.tool_policy.is_disabled(phase_id):
            continue
        entry = cfg.tool_policy.phases.get(phase_id)
        if entry is not None:
            if not entry:
                continue
            entry[:] = ["read", "write", "edit", "recon"]
        else:
            if not phase.tools:
                continue
            phase.tools = ["read", "write", "edit", "recon"]


def _apply_toolset_env(cfg: AgentConfig) -> None:
    """Arm selection: the AGENT_TOOLSET env var (named toolset arms).

    When set (and non-empty) it is the SOLE driver of the arm mutation
    (arm ``baseline`` is a no-op: the packaged config already carries the
    baseline tool policy, so nothing to force). A valid arm applies its
    config mutation and is recorded in ``cfg.arm``; an invalid value is
    ignored (the config stays at the baseline) so arm selection can never
    crash the run. Unset = plain baseline.
    """
    raw = os.environ.get(TOOLSET_ENV)
    if raw is None or not raw.strip():
        return
    from shlepa_agent.toolsets import apply_arm, resolve_arm

    try:
        arm = resolve_arm(raw)
    except ValueError:
        return
    apply_arm(cfg, arm)


def load_config(path: Path | str | None = None) -> AgentConfig:
    """Load the agent config: packaged config.toml + env overrides."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    cfg = AgentConfig.model_validate(data)
    _apply_env_overrides(cfg)
    _apply_toolset_env(cfg)
    return cfg
