"""Commit phase: the emergency/terminal phase.

Resumes the SAME conversation (trimmed message history) with the commit
prompt under a hard time cap. Its toolset, request cap and time cap come
from ``[phases.commit]``. Terminal: ``route`` always returns None.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from shlepa_agent.phases.base import Phase, PhaseResult, RunState
from shlepa_agent.template import load_prompt, render_user


def trim_history(messages: list[Any]) -> list[Any]:
    """Build a safe message history for the commit-phase run.

    - Drop the trailing user/retry prompt (the commit prompt replaces it).
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
        # The task block is repeated only when there is no history to resume
        # (otherwise the task is already in the conversation).
        contents: dict[str, str] = {"phase_prompt": load_prompt(f"{self.id}.md")}
        if not self.history(state):
            contents["task"] = state.task
        return render_user(state.cfg, self.id, contents)

    def route(self, result: PhaseResult, state: RunState) -> str | None:
        return None
