"""Emergency phase — UNUSED in v5 (kept in code, unwired).

The v4 runner reached this phase when the clock crossed
``[agent].commit_deadline`` at a phase boundary. In v5 the routing is
hard-off: the review (commit) phase is the only terminal handler, and time
pressure is expressed through the fixed regime caps (budget.py) and the
one-shot final_ask. The class and its config section remain for
compatibility; nothing in the runner routes to it.

(Original role: terminal rescue — continued the current conversation,
free text output, full toolset, low reasoning effort, capped at the
remaining hard_time window, never retried.)
"""

from __future__ import annotations

from typing import Any

from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.phases.commit import trim_history
from shlepa_agent.template import load_prompt, render_user


class EmergencyPhase(Phase):
    id = "emergency"
    terminal = True

    def history(self, state: RunState) -> list[Any] | None:
        return trim_history(state.model.last_messages)

    def prompt(self, state: RunState) -> str:
        return render_user(
            state.cfg, self.id, {"phase_prompt": load_prompt(f"{self.id}.md")}
        )
