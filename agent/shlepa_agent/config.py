"""Typed agent configuration for the v2 architecture.

Single source of tuning values: ``shlepa_agent/config.toml`` (shipped inside
the package, carried by the submission zip). Environment variables override
individual keys (``SHLEPA_*`` names; the legacy ``AGENT_*`` names were
dropped with the v2 architecture — see ``docs/agent-config.md`` for the
mapping; ``AGENT_CODE_SEARCH`` is the one deliberate exception, wired in
``_apply_code_search_env``). Invalid env values are ignored, matching the
old ``_env_*`` helpers.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"


class AgentSection(BaseModel):
    """Run-level settings: pipeline entry, emergency phase, step guard.

    v5: there is NO task time limit T and NO cycle cap — the agent works in
    plan/work/review cycles until the review verdict is "done"; a new round
    starts on every "next_round" verdict.
    """

    #: Entry phase. Empty = "plan".
    entry: str = ""
    #: Name of the emergency phase (UNUSED in v5, kept for compatibility).
    emergency: str = "emergency"
    # Total phase-run guard (dev knob). 0 = off — the run cycles until done.
    max_steps: int = Field(default=0, ge=0)
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
    # Code-search tools: OFF by default. ``AGENT_CODE_SEARCH`` (rg | sifs)
    # enables them and picks the engine (see _apply_code_search_env). The
    # ``timeout`` is the per-call wall clock (the v5 regime bash cap; the
    # engine's own 60s rg wall is too high for a tool call).
    code_search: ToolConfig = ToolConfig(enabled=False, timeout=30.0)
    file_outline: ToolConfig = ToolConfig(enabled=False, timeout=30.0)
    # Forensics tools: OFF by default. The AGENT_TOOLSET=+forensics arm
    # enables them (see _enable_forensics_tools and toolsets.py). The
    # ``timeout`` is the per-call wall (the v5 regime bash cap); the engine
    # result is separately capped at ``max_output`` chars.
    log_triage: ToolConfig = ToolConfig(enabled=False, timeout=30.0, max_output=3500)
    # MITRE KB tool: OFF by default. The AGENT_TOOLSET=+mitre-kb arm enables
    # it (see _enable_mitre_kb_tools and toolsets.py). The ``timeout`` is a
    # per-call wall safety net (the in-memory search is sub-millisecond);
    # the result is capped at ``max_output`` chars.
    mitre_kb: ToolConfig = ToolConfig(enabled=False, timeout=30.0, max_output=8000)

    def get(self, name: str) -> ToolConfig:
        try:
            return getattr(self, name)
        except AttributeError:
            raise KeyError(f"unknown tool: {name}") from None


class CodeSearchConfig(BaseModel):
    """Engine selection for the code_search/file_outline tools.

    Off by default: no section for this lives in config.toml, and the tools
    are absent unless ``AGENT_CODE_SEARCH`` is set (see
    ``_apply_code_search_env``). Keeping the switch in the env (not the
    toml) is what makes the default agent byte-identical to the baseline.
    """

    #: Engine: "auto" (default = tools off), "rg" (ripgrep fixed-string
    #: scan), or "sifs" (bundled SIFS, BM25-offline).
    engine: str = "auto"


class BlockWrapper(BaseModel):
    """Optional before/after text wrapping one template block."""

    before: str = ""
    after: str = ""


class PhaseConfig(BaseModel):
    """One phase of the pipeline: toolset, hard/advisory limits, template
    overrides.

    - ``time``: explicit hard wall-clock cap for the phase run. ``None``
      (omitted) = the fixed regime constant for the phase (``budget.py``).
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
    code_search: CodeSearchConfig = Field(default_factory=CodeSearchConfig)
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
    "SHLEPA_CODE_SEARCH_TIMEOUT": ("tools.code_search.timeout", float),
    "SHLEPA_LOG_TRIAGE_TIMEOUT": ("tools.log_triage.timeout", float),
    "SHLEPA_LOG_TRIAGE_MAX_OUTPUT": ("tools.log_triage.max_output", int),
    "SHLEPA_MITRE_KB_MAX_OUTPUT": ("tools.mitre_kb.max_output", int),
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


#: The two deliberate AGENT_* env vars (the legacy set was dropped in v2):
#: AGENT_CODE_SEARCH is the legacy dev switch for the code-search tools;
#: AGENT_TOOLSET is the named-arm selector (see toolsets.py) and wins over
#: it when set.
CODE_SEARCH_ENV = "AGENT_CODE_SEARCH"
CODE_SEARCH_ENGINES = ("rg", "sifs")
TOOLSET_ENV = "AGENT_TOOLSET"


def _enable_search_tools(cfg: AgentConfig, engine: str) -> None:
    """Enable code_search/file_outline on the given engine.

    Shared mutation for the legacy AGENT_CODE_SEARCH switch and the named
    toolset arms (``toolsets.apply_arm``): both tools enabled, engine
    stored, and the tool names appended to every phase's tool list (their
    notes then render into the system prompt automatically). Deduped, so
    it is safe if a phase list ever names them explicitly.
    """
    cfg.code_search.engine = engine
    cfg.tools.code_search.enabled = True
    cfg.tools.file_outline.enabled = True
    for phase in cfg.phases.values():
        for name in ("code_search", "file_outline"):
            if name not in phase.tools:
                phase.tools.append(name)


def _enable_forensics_tools(cfg: AgentConfig) -> None:
    """Enable the forensics tool family (the +forensics arm mutation).

    Mirrors :func:`_enable_search_tools`: tools enabled and their names
    appended to every phase's tool list (their notes then render into the
    system prompt automatically). Deduped, so it is safe if a phase list
    ever names them explicitly.
    """
    cfg.tools.log_triage.enabled = True
    for phase in cfg.phases.values():
        if "log_triage" not in phase.tools:
            phase.tools.append("log_triage")


def _enable_mitre_kb_tools(cfg: AgentConfig) -> None:
    """Enable the MITRE KB tool (the +mitre-kb arm mutation).

    Mirrors :func:`_enable_forensics_tools`: tool enabled and its name
    appended to every phase's tool list (its note then renders into the
    system prompt automatically; the arm-gated KB prefix is appended in
    ``runner._system_prompt``). Deduped, so it is safe if a phase list
    ever names it explicitly.
    """
    cfg.tools.mitre_kb.enabled = True
    for phase in cfg.phases.values():
        if "mitre_kb" not in phase.tools:
            phase.tools.append("mitre_kb")


def _apply_code_search_env(cfg: AgentConfig) -> None:
    """Enable code_search/file_outline from AGENT_CODE_SEARCH (rg | sifs).

    Unset or an invalid value leaves the config untouched (tools off,
    baseline byte-identical). Superseded by AGENT_TOOLSET when that is
    set (see :func:`_apply_toolset_env`).
    """
    raw = os.environ.get(CODE_SEARCH_ENV)
    if raw is None or not raw.strip():
        return
    engine = raw.strip().lower()
    if engine not in CODE_SEARCH_ENGINES:
        return  # invalid value: ignore, tools stay off
    _enable_search_tools(cfg, engine)


def _apply_toolset_env(cfg: AgentConfig) -> None:
    """Arm selection: the AGENT_TOOLSET env var (named toolset arms).

    When set (and non-empty) it is the SOLE driver of the code-search
    toolset — the legacy AGENT_CODE_SEARCH switch is skipped even if it
    is also set (so arm=baseline forces the tools off). A valid arm
    applies its config mutation and is recorded in ``cfg.arm``; an
    invalid value is ignored (the config stays at the baseline) so arm
    selection can never crash the run.
    """
    raw = os.environ.get(TOOLSET_ENV)
    if raw is None or not raw.strip():
        _apply_code_search_env(cfg)
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
