"""Phase protocol and shared run state.

A phase is one stage of the 4-phase pipeline: plan, work, commit,
emergency. The runner walks the graph (see ``runner.py``); phases declare
their toolset and limits from the config (``[phases.<id>]``) — the phase
code must not contain budget numbers.

``PhaseResult`` is the structured outcome of a phase run, stored in
``RunState.results`` under the phase id. For phases with an
``output_type`` the typed result (PlanResult/WorkResult) lives in
``result.output`` and ``result.summary`` carries its JSON dump; for
free-text phases ``summary`` is the final answer text.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from shlepa_agent.config import AgentConfig
from shlepa_agent.model import TrackedModel
from shlepa_agent.tools import AgentDeps

#: Minimum useful commit window (seconds): below this, the commit phase is
#: not worth running and the emergency rescue takes over instead.
COMMIT_MIN_S = 30.0


class PhaseResult(BaseModel):
    """Structured, JSON-serializable outcome of one phase run.

    ``status``:
      - "done": the phase finished its job;
      - "budget": the phase was cut off by a budget/limit breach (a normal
        hand-off, never retried);
      - "error": the phase failed after its retries.
    """

    status: str = "done"
    summary: str = ""
    deliverable: str | None = None
    #: Typed phase output (PlanResult/WorkResult); None for free-text phases.
    output: Any | None = None
    error: str | None = None
    iteration: int | None = None


@dataclass(frozen=True)
class PhaseLimits:
    """Limits for one phase, from ``[phases.<id>]``.

    ``time``: hard wall-clock cap for the phase run; ``None`` = until the
    global hard_time (terminal phases take the remainder). ``soft_time`` /
    ``soft_tokens``: advisory only — rendered into the prompt/status, never
    enforced.
    """

    requests: int
    time: float | None = None
    soft_time: float | None = None
    soft_tokens: int | None = None
    reasoning_effort: str | None = None


@dataclass
class RunState:
    """Everything a phase may need, shared across the pipeline."""

    task: str
    deps: AgentDeps
    model: TrackedModel
    results: dict[str, PhaseResult] = field(default_factory=dict)
    #: Completed plan->work cycles (replan count).
    cycles: int = 0

    @property
    def cfg(self) -> AgentConfig:
        return self.deps.cfg


class Phase(ABC):
    """One stage of the pipeline.

    ``id`` must match a ``[phases.<id>]`` section in the agent config.
    """

    id: str
    #: Typed output model (pydantic-ai ``output_type``); None = free text.
    output_type: type[BaseModel] | None = None
    #: Terminal phases (commit, emergency) end the run.
    terminal: bool = False

    # -- config-driven defaults ------------------------------------------
    def tools(self, cfg: AgentConfig) -> list[str]:
        return cfg.phases[self.id].tools

    def limits(self, cfg: AgentConfig) -> PhaseLimits:
        p = cfg.phases[self.id]
        return PhaseLimits(
            requests=p.requests,
            time=p.time,
            soft_time=p.soft_time,
            soft_tokens=p.soft_tokens,
            reasoning_effort=p.reasoning_effort,
        )

    def limits_note(self, state: RunState) -> str:
        """Time-budget line rendered into the phase prompt.

        With an adaptive budget (``state.deps.budget``) the caps are derived
        from the task limit T; without one (legacy/test context) the static
        phase config values are used.
        """
        cfg = state.cfg
        b = state.deps.budget
        l = self.limits(cfg)
        parts: list[str] = []
        if b is not None:
            parts.append(f"task time limit T={b.T:.0f}s")
            if self.id == "plan":
                parts.append(f"this phase is hard-capped at {b.plan:.0f}s")
                parts.append(f"aim to finish within {max(10.0, b.plan - 10.0):.0f}s")
            elif self.id == "work":
                parts.append(f"this cycle is hard-capped at {b.work:.0f}s")
                parts.append(f"this is cycle {state.cycles + 1} of at most {b.max_cycles}")
            elif self.id == "commit":
                cap = min(b.commit_cap, max(0.0, b.hard - state.model.elapsed()))
                parts.append(f"this phase is hard-capped at {max(cap, 1.0):.0f}s")
        else:
            if l.time is not None:
                parts.append(f"this phase is hard-capped at {l.time:.0f}s")
            if l.soft_time is not None:
                parts.append(f"aim to finish within {l.soft_time:.0f}s")
        if l.soft_tokens is not None:
            parts.append(f"keep the output lean (soft budget ~{l.soft_tokens} tokens)")
        return "; ".join(parts)

    # -- to implement -----------------------------------------------------
    @abstractmethod
    def prompt(self, state: RunState) -> str:
        """The user message that starts this phase's run."""

    def history(self, state: RunState) -> list[Any] | None:
        """Message history to resume from, or None for a fresh run."""
        return None

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<phase {self.id}>"
