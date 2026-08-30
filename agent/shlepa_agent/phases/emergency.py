"""Emergency phase: terminal rescue when the commit deadline is passed.

Reached only when the clock has crossed ``[agent].commit_deadline`` at a
phase boundary while the next phase is not commit. Continues the current
conversation (whatever exists), free text output, full toolset, low
reasoning effort. The runner caps it at the remaining hard_time window.
Never retried.
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
