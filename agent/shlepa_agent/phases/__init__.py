"""Phase registry.

Phase ids are config-driven (``[agent].entry`` / ``[agent].emergency`` and
the ``[phases.*]`` sections); the registry maps id -> phase class.
"""

from __future__ import annotations

from shlepa_agent.phases.base import Phase, PhaseLimits, PhaseResult, RunState
from shlepa_agent.phases.commit import CommitPhase, trim_history
from shlepa_agent.phases.explore import ExplorePhase

PHASES: dict[str, type[Phase]] = {
    ExplorePhase.id: ExplorePhase,
    CommitPhase.id: CommitPhase,
}


def get_phase(phase_id: str) -> Phase:
    try:
        return PHASES[phase_id]()
    except KeyError:
        raise KeyError(f"unknown phase: {phase_id}") from None


__all__ = [
    "PHASES",
    "CommitPhase",
    "ExplorePhase",
    "Phase",
    "PhaseLimits",
    "PhaseResult",
    "RunState",
    "get_phase",
    "trim_history",
]
