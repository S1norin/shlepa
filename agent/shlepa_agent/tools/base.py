"""Shared types for the modular tool system."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from shlepa_agent.config import AgentConfig


@dataclass(frozen=True)
class AgentDeps:
    """Per-run dependencies handed to every tool call via RunContext.deps."""

    workdir: Path
    cfg: "AgentConfig"


@dataclass(frozen=True)
class Tool:
    """One agent tool: name, short usage note, async implementation.

    ``run`` has the pydantic-ai tool signature
    ``(ctx: RunContext[AgentDeps], **args) -> str``. Its docstring is the
    tool description sent to the model in the API tool spec; ``note`` is a
    one-line usage hint rendered into the request template's ``tools`` block.
    """

    name: str
    note: str
    run: Callable[..., Any]


def resolve_path(path: str, workdir: Path) -> Path:
    if Path(path).is_absolute():
        return Path(path).resolve()
    return (workdir / path).resolve()
