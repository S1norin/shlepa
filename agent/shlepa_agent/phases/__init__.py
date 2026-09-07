"""Phase registry.

Phase ids are config-driven (``[agent].entry`` / ``[agent].emergency`` and
the ``[phases.*]`` sections); the registry maps id -> phase class.
"""

from __future__ import annotations

from shlepa_agent.phases.base import Phase, PhaseLimits, PhaseResult, RunState
from shlepa_agent.phases.commit import CommitPhase, RepairPhase, trim_history
from shlepa_agent.phases.emergency import EmergencyPhase
from shlepa_agent.phases.plan import PlanPhase
from shlepa_agent.phases.review import ReviewPhase
from shlepa_agent.phases.salvage import SalvagePhase
from shlepa_agent.phases.work import WorkPhase

PHASES: dict[str, type[Phase]] = {
    PlanPhase.id: PlanPhase,
    WorkPhase.id: WorkPhase,
    ReviewPhase.id: ReviewPhase,
    # Disabled in the v6-rewrite regime (files kept for re-enable): the
    # runner never routes to them.
    SalvagePhase.id: SalvagePhase,
    CommitPhase.id: CommitPhase,
    RepairPhase.id: RepairPhase,
    EmergencyPhase.id: EmergencyPhase,
}


def get_phase(phase_id: str) -> Phase:
    try:
        return PHASES[phase_id]()
    except KeyError:
        raise KeyError(f"unknown phase: {phase_id}") from None


__all__ = [
    "PHASES",
    "CommitPhase",
    "EmergencyPhase",
    "Phase",
    "PhaseLimits",
    "PhaseResult",
    "PlanPhase",
    "RepairPhase",
    "ReviewPhase",
    "RunState",
    "SalvagePhase",
    "WorkPhase",
    "get_phase",
    "trim_history",
]
