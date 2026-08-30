"""Phase protocol and run state.

A phase is one stage of the agent pipeline (explore, commit, future
verify/fix). The runner (core.run_prompt) walks the phase graph:

    entry phase -> run -> PhaseResult -> route() -> next phase id | None

Phases declare their toolset and limits from the config
(``[phases.<id>]``); the phase code must not contain budget numbers.

``PhaseResult`` is the structured, JSON-serializable outcome of a phase run;
one per phase, stored in ``RunState.results``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from shlepa_agent.config import AgentConfig
from shlepa_agent.model import TrackedModel
from shlepa_agent.tools import AgentDeps


class PhaseResult(BaseModel):
    """Structured outcome of one phase run (JSON-serializable).

    ``status``:
      - "done": the phase finished its job;
      - "budget": the phase was cut off by a budget/limit breach;
      - "error": the phase failed (model error, unexpected exception).
    ``deliverable``: path (relative to the workdir) of the produced
    deliverable, when the phase can name one. ``iteration``: loop index for
    future verify/fix iterations (None on the first pass).
    """

    status: str = "done"
    summary: str = ""
    deliverable: str | None = None
    iteration: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class PhaseLimits:
    """Wall-clock window and request cap for one phase, from [phases.<id>].

    For regular phases ``time`` is a soft window (a breach routes to the
    emergency phase); for the emergency phase it is a hard cap (the runner
    stops the run when it expires).
    """

    requests: int
    time: float
    reasoning_effort: str | None = None
    terminal: bool = False


@dataclass
class RunState:
    """Everything a phase may need, shared across the pipeline."""

    task: str
    deps: AgentDeps
    model: TrackedModel
    results: dict[str, PhaseResult] = field(default_factory=dict)

    @property
    def cfg(self) -> AgentConfig:
        return self.deps.cfg


class Phase(ABC):
    """One stage of the pipeline.

    ``id`` must match a ``[phases.<id>]`` section in the agent config.
    """

    id: str

    # -- config-driven defaults ------------------------------------------
    def tools(self, cfg: AgentConfig) -> list[str]:
        return cfg.phases[self.id].tools

    def limits(self, cfg: AgentConfig) -> PhaseLimits:
        p = cfg.phases[self.id]
        return PhaseLimits(
            requests=p.requests,
            time=p.time,
            reasoning_effort=p.reasoning_effort,
            terminal=self.terminal,
        )

    # -- to implement -----------------------------------------------------
    @abstractmethod
    def prompt(self, state: RunState) -> str:
        """The user message that starts this phase's run."""

    def history(self, state: RunState) -> list[Any] | None:
        """Message history to resume from, or None for a fresh run."""
        return None

    @abstractmethod
    def route(self, result: PhaseResult, state: RunState) -> str | None:
        """Next phase id after this phase, or None when the run is over."""

    # -- flags ------------------------------------------------------------
    #: The emergency phase has a hard time cap and is terminal.
    terminal: bool = False

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<phase {self.id}>"
