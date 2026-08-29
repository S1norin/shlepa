"""Write tool: create a NEW file with exact content (never overwrites)."""

from __future__ import annotations

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, resolve_path


async def write(ctx: "RunContext[AgentDeps]", path: str, text: str) -> str:
    """Write exact content to a NEW file. The path must not exist yet;
    parent directories are created. Nothing is added to the content (no
    trailing newline). To change an existing file, use edit."""
    p = resolve_path(path, ctx.deps.workdir)
    _log_event("tool_call", tool="write", path=str(p))
    if p.exists():
        return f"File already exists (use edit to change it): {path}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return f"Wrote {len(text)} chars to {path}"


WRITE_TOOL = Tool(
    name="write",
    note="write: create a NEW file with exact content (never overwrites; "
    "parent dirs created; no trailing newline added).",
    run=write,
)
