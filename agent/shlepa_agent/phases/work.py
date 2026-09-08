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
        if plan is not None:
            if plan.output is not None:
                prev_parts.append("plan phase result:\n" + plan.summary)
            elif plan.note:
                # The plan phase was cut by its cap but left a text plan in
                # its one-shot final_ask message; work executes it.
                prev_parts.append(
                    "plan phase hit its time cap and left this plan in its "
                    "final message (plain text, may be incomplete):\n"
                    + plan.note
                    + "\nTreat it as the plan for this cycle; where it is "
                    "incomplete, make the smallest sensible decision "
                    "yourself."
                )
            elif plan.error:
                # The plan phase ended without a plan (time cap / error):
                # say so explicitly, otherwise work.md's "execute the plan
                # and do not invent new approaches" has no plan to point at.
                prev_parts.append(
                    "plan phase did not produce a plan (" + plan.error + "): "
                    "there is no plan for this cycle. Derive the minimum "
                    "work directly from the task instruction and proceed; "
                    "do not pretend a plan exists."
                )
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
