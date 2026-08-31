"""Plan phase: understand the task and the environment, produce a plan.

No real work is done here — at most a few cheap reads to confirm
assumptions. Every plan run is fresh (no history); on a replan cycle the
previous work result arrives in the ``previous_results`` user-message
block. Ends with a structured ``PlanResult`` (pydantic output tool).
"""

from __future__ import annotations

from typing import Any

from shlepa_agent.outputs import PlanResult, output_schema_note
from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.template import load_prompt, render_user


class PlanPhase(Phase):
    id = "plan"
    output_type = PlanResult
    terminal = False

    def prompt(self, state: RunState) -> str:
        cfg = state.cfg
        contents: dict[str, str] = {
            "phase_prompt": load_prompt("plan.md"),
            "extra": self.limits_note(state),
            "output_schema": output_schema_note(PlanResult),
        }
        parts: list[str] = []
        prev = state.results.get("work")
        if prev is not None:
            if prev.output is not None:
                parts.append("work phase (previous cycle) result:\n" + prev.summary)
            elif prev.error:
                parts.append(
                    "work phase (previous cycle) failed with:\n" + prev.error
                )
        review = state.results.get("commit")
        if review is not None and review.output is not None:
            hints = getattr(review.output, "hints", None) or []
            if hints:
                parts.append(
                    "review phase verdict (previous cycle): next_round — "
                    "follow these hints in the new plan:\n"
                    + "\n".join(f"- {h}" for h in hints)
                )
        if parts:
            contents["previous_results"] = "\n\n".join(parts)
        return render_user(cfg, self.id, contents)

    def history(self, state: RunState) -> list[Any] | None:
        return None  # fresh conversation per plan run (replan included)
