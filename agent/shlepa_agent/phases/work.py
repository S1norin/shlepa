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
            elif plan.status == "timeout":
                prev_parts.append(
                    "the plan phase was cut off by its time cap before "
                    "producing a plan"
                )
            elif plan.status == "error":
                prev_parts.append(
                    "the plan phase failed ("
                    + (plan.error or "unknown error")
                    + "); there is no plan — execute the task directly "
                    "from the task statement and the evidence below"
                )
        handoff = getattr(state, "plan_handoff", None)
        if handoff:
            hand_parts: list[str] = []
            if handoff.get("handoff"):
                hand_parts.append(
                    "PARTIAL HANDOFF (typed summary of the cut-off plan "
                    "phase):\n" + handoff["handoff"]
                )
            from shlepa_agent.state import render_last_tools  # lazy: circular

            lt = render_last_tools(handoff.get("last_tools") or [])
            if lt:
                hand_parts.append(lt)
            if hand_parts:
                prev_parts.append("\n\n".join(hand_parts))
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
