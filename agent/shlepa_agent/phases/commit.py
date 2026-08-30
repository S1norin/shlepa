"""Commit phase: terminal deliverable phase.

Continues the CURRENT conversation (trimmed message history) so the model
keeps its full context (the work run, or the plan run on the trivial
plan->commit shortcut). The user message asks to finalize and verify the
deliverable now. Free text output; takes the remainder of the trial
(``time`` omitted in config -> the runner caps it at the global hard_time).
Never retried.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.template import load_prompt, render_user


def trim_history(messages: list[Any]) -> list[Any]:
    """Build a safe message history for a continuation run.

    - Drop the trailing user/retry prompt (the new user message replaces it).
    - Drop a trailing model response with unpaired tool calls (would 400).
    A trailing tool-return request is kept: it is a valid open state.
    """
    msgs = list(messages)
    if msgs and isinstance(msgs[-1], ModelRequest):
        has_tool_return = any(isinstance(p, ToolReturnPart) for p in msgs[-1].parts)
        if not has_tool_return:
            msgs.pop()
    while msgs and isinstance(msgs[-1], ModelResponse):
        if any(isinstance(p, ToolCallPart) for p in msgs[-1].parts):
            msgs.pop()
            continue
        break
    return msgs


class CommitPhase(Phase):
    id = "commit"
    terminal = True

    def history(self, state: RunState) -> list[Any] | None:
        return trim_history(state.model.last_messages)

    def prompt(self, state: RunState) -> str:
        # The task is already in the system message (and in the resumed
        # history), so the user message carries only the phase instructions.
        return render_user(
            state.cfg, self.id, {"phase_prompt": load_prompt(f"{self.id}.md")}
        )
