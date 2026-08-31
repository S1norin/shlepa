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

from shlepa_agent.budget import (
    TOKEN_FALLBACK,
    Budget,
    _coerce_form,
    derive_budget,
    extract_time_limit,
    extract_token_limit,
)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class AgentSection(BaseModel):
    """Run-level settings: pipeline entry, emergency phase, cycle cap, deadline.

    Zero/empty values mean "derive from the adaptive task budget" (see
    ``budget.build_budget``); explicit positive values are overrides.
    """

    #: Entry phase. Empty = derived: "plan" when the budget allows a plan
    #: phase, otherwise "work".
    entry: str = ""
    emergency: str = "emergency"
    # Max plan->work cycles; after the cap a replan request is forced into
    # commit. 0 = derived from the budget.
    max_cycles: int = Field(default=0, ge=0)
    # Commit deadline: if the clock has passed this point at a phase boundary
    # and the next phase is not commit, the emergency phase runs instead.
    # 0 = derived (plan + work + commit cap, capped by hard - reserve).
    commit_deadline: float = 0.0
    # Total phase-run guard (plan/work cycles + terminal phase).
    # 0 = derived (2 * max_cycles + 2).
    max_steps: int = Field(default=0, ge=0)
    #: Sampling temperature; sent to the endpoint only when ``send_temp``
    #: is enabled (default: the endpoint decides).
    temp: float = 0.6
    #: Send ``temp`` in model settings (env: SHLEPA_SEND_TEMP, 1/0).
    send_temp: bool = False


class BudgetConfig(BaseModel):
    """Global budget: static reference values + adaptive form.

    The runtime budget is DERIVED per run from the task time limit T via
    ``build_budget`` (env / task.toml / instruction text / ``t_fallback``).
    ``hard_time`` / ``soft_time`` / ``token_budget`` are reference values for
    the default 600s task (kept for logging/back-compat and for legacy
    runs without a derived budget); ``request_limit``, ``max_tokens``,
    ``request_timeout`` and ``request_wall`` are always-enforced global caps.
    ``form`` overrides the derivation knobs (see ``budget.BudgetForm``).
    """

    hard_time: float = 585.0
    soft_time: float = 500.0
    #: Task limit T used when no limit is detected from env / task.toml /
    #: instruction text.
    t_fallback: float = 600.0
    request_limit: int = 90
    token_budget: int = 300_000
    #: Derivation-form overrides (BudgetForm fields); unknown keys are
    #: ignored, omitted keys keep their defaults.
    form: dict = Field(default_factory=dict)
    # Hard per-request output cap; without it a single request can loop for
    # tens of thousands of tokens and eat the whole trial before commit.
    max_tokens: int = 16_384
    request_timeout: float = 180.0
    # Kill a single in-flight request if it runs this long (open -> last
    # chunk). Prevents one very slow generation from eating the whole budget.
    request_wall: float = 240.0


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
    "SHLEPA_MAX_CYCLES": ("agent.max_cycles", int),
    "SHLEPA_COMMIT_DEADLINE": ("agent.commit_deadline", float),
    "SHLEPA_BUDGET_HARD_TIME": ("budget.hard_time", float),
    "SHLEPA_BUDGET_SOFT_TIME": ("budget.soft_time", float),
    "SHLEPA_BUDGET_T_FALLBACK": ("budget.t_fallback", float),
    "SHLEPA_BUDGET_REQUEST_LIMIT": ("budget.request_limit", int),
    "SHLEPA_BUDGET_TOKEN_BUDGET": ("budget.token_budget", int),
    "SHLEPA_BUDGET_MAX_TOKENS": ("budget.max_tokens", int),
    "SHLEPA_BUDGET_REQUEST_TIMEOUT": ("budget.request_timeout", float),
    "SHLEPA_BUDGET_REQUEST_WALL": ("budget.request_wall", float),
    "SHLEPA_BASH_TIMEOUT": ("tools.bash.timeout", float),
    "SHLEPA_BASH_MAX_TIMEOUT": ("tools.bash.max_timeout", float),
    "SHLEPA_BASH_MAX_OUTPUT": ("tools.bash.max_output", int),
    "SHLEPA_READ_MAX_LIMIT": ("tools.read.max_limit", int),
    "SHLEPA_READ_MAX_OUTPUT": ("tools.read.max_output", int),
    "SHLEPA_COMMIT_TIME": ("phases.commit.time", float),
    "SHLEPA_COMMIT_REQUEST_LIMIT": ("phases.commit.requests", int),
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
    """Derive the per-run adaptive budget from the config + task instruction.

    T resolution: env (``SLEPA_AGENT_TIMEOUT`` first) -> task.toml probe ->
    instruction text -> ``budget.t_fallback``. Token limit: env -> text ->
    the form fallback (95% of it becomes the run token budget).
    """
    form = _coerce_form(cfg.budget.form)
    t, source = extract_time_limit(instruction)
    if source == "fallback" and cfg.budget.t_fallback != form.t_fallback:
        t, source = cfg.budget.t_fallback, "config:default"
    elif source == "fallback":
        source = "config:default"
    token_limit, token_source = extract_token_limit(instruction)
    if token_source == "fallback" and form.token_fallback != TOKEN_FALLBACK:
        token_limit, token_source = form.token_fallback, "config:default"
    return derive_budget(
        t,
        token_limit=token_limit,
        source=source,
        token_source=token_source,
        request_limit=cfg.budget.request_limit,
        form=form,
    )
