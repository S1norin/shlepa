"""Modular tool system: one module per tool + a config-driven registry.

A tool is a ``Tool`` record (name, short usage note, async run function with
the pydantic-ai signature). ``get_tools`` resolves a phase's configured tool
list against the enabled flags in the agent config, so adding or removing a
tool is a config change (plus one module here for brand-new tools).
"""

from __future__ import annotations

from shlepa_agent.config import AgentConfig
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path
from shlepa_agent.tools.bash import BASH_TOOL
from shlepa_agent.tools.code_search import CODE_SEARCH_TOOL, FILE_OUTLINE_TOOL
from shlepa_agent.tools.edit import EDIT_TOOL
from shlepa_agent.tools.log_triage import LOG_TRIAGE_TOOL
from shlepa_agent.tools.mitre_kb import MITRE_KB_TOOL
from shlepa_agent.tools.read import READ_TOOL
from shlepa_agent.tools.recon import RECON_TOOL
from shlepa_agent.tools.write import WRITE_TOOL

ALL_TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        READ_TOOL,
        WRITE_TOOL,
        EDIT_TOOL,
        BASH_TOOL,
        # Off by default: registered only when AGENT_CODE_SEARCH is set
        # (the config layer enables them and appends the names to the
        # phase tool lists; get_tools skips disabled tools).
        CODE_SEARCH_TOOL,
        FILE_OUTLINE_TOOL,
        # Off by default: enabled by the +forensics toolset arm
        # (config._enable_forensics_tools).
        LOG_TRIAGE_TOOL,
        # Off by default: enabled by the +mitre-kb toolset arm
        # (config._enable_mitre_kb_tools).
        MITRE_KB_TOOL,
        # Off by default: enabled by the +recon toolset arm
        # (config._enable_recon_tools).
        RECON_TOOL,
    )
}

__all__ = ["ALL_TOOLS", "AgentDeps", "Tool", "get_tools", "resolve_path"]


def get_tools(cfg: AgentConfig, names: list[str]) -> list[Tool]:
    """Resolve a tool list from config; disabled tools are skipped.

    Raises KeyError on an unknown tool name (a config bug, fail fast).
    """
    tools: list[Tool] = []
    for name in names:
        if name not in ALL_TOOLS:
            raise KeyError(f"unknown tool: {name}")
        if not cfg.tools.get(name).enabled:
            continue
        tools.append(ALL_TOOLS[name])
    return tools
