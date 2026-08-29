"""Explore phase: the main working phase.

Fresh run (no history). Its toolset, request cap and soft time window come
from ``[phases.explore]``. Routing:
  - done   -> run is over (None)
  - budget -> emergency phase (commit)
  - error  -> emergency phase (commit)
"""

from __future__ import annotations

from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.template import load_prompt, render_user


class ExplorePhase(Phase):
    id = "explore"

    def prompt(self, state: RunState) -> str:
        return render_user(
            state.cfg,
            self.id,
            {"task": state.task, "phase_prompt": load_prompt(f"{self.id}.md")},
        )

    def route(self, result: PhaseResult, state: RunState) -> str | None:
        if result.status == "done":
            return None
        # budget or error: hand off to the emergency (commit) phase.
        return state.cfg.agent.emergency
