"""Work phase: execute the plan, self-review, decide commit or replan.

Every work run is fresh: the plan (and, on a retry/replan, the previous
attempt) arrives in the ``previous_results`` user-message block. Ends with
a structured ``WorkResult`` (pydantic output tool).
"""

from __future__ import annotations

from typing import Any

from shlepa_agent.outputs import WorkResult, output_schema_note
from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.template import load_prompt, render_user


class WorkPhase(Phase):
    id = "work"
    output_type = WorkResult
    terminal = False

    def prompt(self, state: RunState) -> str:
        cfg = state.cfg
        contents: dict[str, str] = {
            "phase_prompt": load_prompt("work.md"),
            "extra": self.limits_note(state),
            "output_schema": output_schema_note(WorkResult),
        }
        prev_parts: list[str] = []
        plan = state.results.get("plan")
        if plan is not None and plan.output is not None:
            prev_parts.append("plan phase result:\n" + plan.summary)
        prev_work = state.results.get("work")
        if prev_work is not None:
            if prev_work.output is not None:
                prev_parts.append("previous work attempt result:\n" + prev_work.summary)
            elif prev_work.error:
                prev_parts.append(
                    "previous work attempt failed with:\n" + prev_work.error
                )
        if prev_parts:
            contents["previous_results"] = "\n\n".join(prev_parts)
        return render_user(cfg, self.id, contents)

    def history(self, state: RunState) -> list[Any] | None:
        return None  # fresh conversation; the plan arrives as context
