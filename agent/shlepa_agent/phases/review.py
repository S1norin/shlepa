"""Review relay phase (v6-rewrite): the hand-off between cycles.

The relay is NOT a judge and does not route: it resumes the just-finished
WORK transcript (no tools — its job is distillation, not exploration),
reads the state of the deliverable, and emits the typed ``ReviewResult``
(summary / done / problems / hints_next). The next cycle's PLAN consumes
the previous work result plus this relay, and the next WORK consumes the
relay as well (plus the fresh plan). It runs after every work cycle
EXCEPT the last (the run ends right after WORK_N -> deliverable_check ->
exit). Hard-capped by the fixed review cap (``budget.py``); never retried.
"""

from __future__ import annotations

from typing import Any

from shlepa_agent.outputs import ReviewResult, output_schema_note
from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.template import load_prompt, render_user


class ReviewPhase(Phase):
    """Toolless distillation of the just-finished work cycle."""

    id = "review"
    output_type = ReviewResult
    terminal = False

    def history(self, state: RunState) -> list[Any] | None:
        # The relay rides on the WORK conversation: it already carries the
        # plan, the tool activity and the final_result. No fresh packet —
        # the transcript IS the context.
        return trim_history(state.model.last_messages) or None

    def prompt(self, state: RunState) -> str:
        cfg = state.cfg
        return render_user(
            cfg,
            self.id,
            {
                "phase_prompt": load_prompt(f"{self.id}.md"),
                "extra": self.limits_note(state),
                "output_schema": output_schema_note(ReviewResult),
            },
        )
