"""Typed agent configuration for the v2 architecture.

Single source of tuning values: ``shlepa_agent/config.toml`` (shipped inside
the package, carried by the submission zip). Environment variables override
individual keys (``SHLEPA_*`` names; the legacy ``AGENT_*`` names were
dropped with the v2 architecture — see ``docs/agent-config.md`` for the
mapping). Invalid env values are ignored, matching the old ``_env_*``
helpers.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from shlepa_agent.budget import Budget, derive_budget, extract_time_limit

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class AgentSection(BaseModel):
    """Run-level settings: pipeline entry, emergency phase, deadline.

    Zero/empty values mean "derive from the per-task budget" (see
    ``build_budget``); explicit positive values are overrides.
    v5: there is NO plan->work cycle cap — the cycle count is time-driven
    (a new round only starts when a full cycle fits the remaining time).
    """

    #: Entry phase. Empty = derived: "plan" when a full cycle (plan + work
    #: + review) fits the remaining time, otherwise "work".
    entry: str = ""
    emergency: str = "emergency"
    # Commit deadline: if the clock has passed this point at a phase boundary
    # and the next phase is not commit, the emergency phase runs instead.
    # 0 = derived (plan + work + review cap, capped by hard).
    commit_deadline: float = 0.0
    # Total phase-run guard (dev knob). 0 = off — time is the bound (v5).
    max_steps: int = Field(default=0, ge=0)
    temp: float = 0.2


class BudgetConfig(BaseModel):
    """Global budget: static reference values for the fixed v5 regime.

    The runtime budget is DERIVED per run from the task time limit T via
    ``build_budget`` (env / task.toml / instruction text / ``t_fallback``);
    the phase caps are fixed constants (``budget.py``). ``hard_time`` /
    ``soft_time`` are reference values for legacy runs without a derived
    budget; ``max_tokens``, ``request_timeout`` and ``request_wall`` are
    per-request caps. There is NO global token budget and NO request-count
    limit (token usage is logged for analysis only).
    """

    hard_time: float = 585.0
    soft_time: float = 500.0
    #: Task limit T used when no limit is detected from env / task.toml /
    #: instruction text.
    t_fallback: float = 600.0
    # Hard per-request output cap; without it a single request can loop for
    # tens of thousands of tokens and eat the whole trial before commit.
    max_tokens: int = 16_384
    request_timeout: float = 180.0
    # Per-request wall (open -> last chunk) for legacy runs without a derived
    # budget; with a budget the regime constant budget.llm_wall (180s) is used.
    request_wall: float = 180.0


class ToolConfig(BaseModel):
    """Per-tool settings. Fields are used where relevant:

    - ``timeout``: bash default per-call timeout (seconds)
    - ``max_timeout``: bash hard cap for the per-call timeout (seconds)
    - ``max_limit``: read max lines per call
    - ``max_output``: hard char cap on the tool result (read: 4000, bash: 16000)
    """

    enabled: bool = True
    timeout: float | None = None
    max_timeout: float | None = None
    max_output: int | None = None
    max_limit: int | None = None


class ToolsConfig(BaseModel):
    bash: ToolConfig = ToolConfig(enabled=True, timeout=30.0, max_timeout=120.0, max_output=16000)
    read: ToolConfig = ToolConfig(enabled=True, max_limit=100, max_output=4000)
    write: ToolConfig = ToolConfig()
    edit: ToolConfig = ToolConfig()

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
    """One phase of the pipeline: toolset, hard/advisory limits, template
    overrides.

    - ``time``: hard wall-clock cap for the phase run. ``None`` (omitted) means
      "until the global hard_time" — used by the terminal phases (commit,
      emergency) which take the remainder of the trial.
    - ``soft_time`` / ``soft_tokens``: advisory only. Rendered into the phase
      prompt and status lines; they never cut the phase.
    """

    tools: list[str] = Field(min_length=1)
    requests: int = Field(ge=1)
    time: float | None = Field(default=None, gt=0)
    soft_time: float | None = Field(default=None, gt=0)
    soft_tokens: int | None = Field(default=None, gt=0)
    reasoning_effort: str | None = None
    max_retries: int = Field(default=2, ge=0)
    # Per-phase template wrapper overrides: block name -> before/after.
    template: dict[str, BlockWrapper] = Field(default_factory=dict)


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
    phases: dict[str, PhaseConfig] = Field(min_length=1)
    template: TemplateConfig = Field(
        default_factory=lambda: TemplateConfig(blocks=["system", "tools", "task"])
    )


#: Env-var overrides: name -> (dotted config path, target type).
ENV_OVERRIDES: dict[str, tuple[str, type]] = {
    "SHLEPA_TEMP": ("agent.temp", float),
    "SHLEPA_MAX_STEPS": ("agent.max_steps", int),
    "SHLEPA_COMMIT_DEADLINE": ("agent.commit_deadline", float),
    "SHLEPA_BUDGET_HARD_TIME": ("budget.hard_time", float),
    "SHLEPA_BUDGET_SOFT_TIME": ("budget.soft_time", float),
    "SHLEPA_BUDGET_T_FALLBACK": ("budget.t_fallback", float),
    "SHLEPA_BUDGET_MAX_TOKENS": ("budget.max_tokens", int),
    "SHLEPA_BUDGET_REQUEST_TIMEOUT": ("budget.request_timeout", float),
    "SHLEPA_BUDGET_REQUEST_WALL": ("budget.request_wall", float),
    "SHLEPA_BASH_TIMEOUT": ("tools.bash.timeout", float),
    "SHLEPA_BASH_MAX_TIMEOUT": ("tools.bash.max_timeout", float),
    "SHLEPA_BASH_MAX_OUTPUT": ("tools.bash.max_output", int),
    "SHLEPA_READ_MAX_LIMIT": ("tools.read.max_limit", int),
    "SHLEPA_READ_MAX_OUTPUT": ("tools.read.max_output", int),
    "SHLEPA_COMMIT_TIME": ("phases.commit.time", float),
    "SHLEPA_COMMIT_REASONING_EFFORT": ("phases.commit.reasoning_effort", str),
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


def load_config(path: Path | str | None = None) -> AgentConfig:
    """Load the agent config: packaged config.toml + env overrides."""
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    cfg = AgentConfig.model_validate(data)
    _apply_env_overrides(cfg)
    return cfg


def build_budget(cfg: AgentConfig, instruction: str = "") -> Budget:
    """Derive the per-run budget: resolve T, apply the fixed v5 regime.

    T resolution: env (``SLEPA_AGENT_TIMEOUT`` first) -> task.toml probe ->
    instruction text -> ``budget.t_fallback``. The phase caps are fixed
    constants (see ``budget.derive_budget``); there is no token limit.
    """
    t, source = extract_time_limit(instruction)
    if source == "fallback":
        t, source = cfg.budget.t_fallback, "config:default"
    return derive_budget(t, source=source)
