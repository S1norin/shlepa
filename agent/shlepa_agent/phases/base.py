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

from shlepa_agent.budget import PLAN_CAP, REVIEW_CAP, WORK_CAP
from shlepa_agent.config import AgentConfig
from shlepa_agent.model import TrackedModel
from shlepa_agent.tools import AgentDeps


class PhaseResult(BaseModel):
    """Structured, JSON-serializable outcome of one phase run.

    ``status``:
      - "done": the phase finished its job;
      - "timeout": the phase was cut off by its time cap / a model context
        limit breach (a normal hand-off, never retried);
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

    ``time``: explicit hard wall-clock cap override; ``None`` = the fixed
    regime constant for the phase (``budget.py``). ``soft_time`` /
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
    #: v6 plan-timeout hand-off payload, set by the runner when a plan
    #: timeout is routed to WORK: {"handoff": <PartialHandoff JSON or None>,
    #: "last_tools": [LAST_TOOLS entries]}. Rendered into the work prompt;
    #: None for normal plans and for ``SHLEPA_HANDOFF=off``.
    plan_handoff: dict[str, Any] | None = field(default=None)
    #: v6 (w2-3): deliverable spec resolved after WORK (from the plan's
    #: artifact_spec / WorkResult.deliverable); None when no path is known.
    deliverable_spec: dict[str, Any] | None = field(default=None)
    #: v6 (w2-3): latest mechanical check result (deliverable_check.py);
    #: refreshed after WORK and again after SALVAGE; consumed by REVIEW.
    deliverable_check: dict[str, Any] | None = field(default=None)
    #: v6 (w2-9): last check-PASSING snapshot of the deliverable
    #: {"path": <relative>, "sha256": <hex>, "content": <text>}; restored
    #: on exit when a later round left a broken file (best-at-exit).
    best_snapshot: dict[str, Any] | None = field(default=None)
    #: v6 (w3-6): in-environment test-file hashes recorded at bootstrap
    #: (tamper guard); None when the task ships no test files.
    test_hashes: dict[str, str] | None = field(default=None)
    #: v6 (w3-6): True when the test files changed mid-run — the run's
    #: own test results are then invalid.
    test_tampered: bool = False

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
        """Time-cap line rendered into the phase prompt (fixed regime).

        The caps are the regime constants (``budget.py``); an explicit
        ``[phases.<id>].time`` value overrides them (dev knob).
        """
        cfg = state.cfg
        lim = self.limits(cfg)
        parts: list[str] = []
        if self.id == "plan":
            cap = lim.time if lim.time is not None else PLAN_CAP
            parts.append(f"this phase is hard-capped at {cap:.0f}s")
        elif self.id == "work":
            cap = lim.time if lim.time is not None else WORK_CAP
            parts.append(f"this cycle is hard-capped at {cap:.0f}s")
            parts.append(f"this is cycle {state.cycles + 1}")
        elif self.id == "commit":  # review phase
            cap = lim.time if lim.time is not None else REVIEW_CAP
            parts.append(f"this phase is hard-capped at {cap:.0f}s")
        else:
            if lim.time is not None:
                parts.append(f"this phase is hard-capped at {lim.time:.0f}s")
        if lim.soft_time is not None:
            parts.append(f"aim to finish within {lim.soft_time:.0f}s")
        if lim.soft_tokens is not None:
            parts.append(f"keep the output lean (soft budget ~{lim.soft_tokens} tokens)")
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
