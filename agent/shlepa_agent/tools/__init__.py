"""Modular tool system: one module per tool + a config-driven registry.

A tool is a ``Tool`` record (name, short usage note, async run function with
the pydantic-ai signature). ``get_tools`` resolves a phase's configured tool
list against the enabled flags in the agent config, so adding or removing a
tool is a config change (plus one module here for brand-new tools).
"""

from __future__ import annotations

from shlepa_agent.config import AgentConfig
from shlepa_agent.tools.append_file import APPEND_FILE_TOOL
from shlepa_agent.tools.apply_diff import APPLY_DIFF_TOOL
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path
from shlepa_agent.tools.bash import BASH_TOOL
from shlepa_agent.tools.read_file import READ_FILE_TOOL
from shlepa_agent.tools.write_file import WRITE_FILE_TOOL

ALL_TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        BASH_TOOL,
        READ_FILE_TOOL,
        WRITE_FILE_TOOL,
        APPEND_FILE_TOOL,
        APPLY_DIFF_TOOL,
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
