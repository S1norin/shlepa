"""Review phase (phase id ``commit``): terminal judge phase (v5).

Continues the CURRENT conversation (trimmed message history) so the model
keeps its full context (the plan + work runs of the current cycle). The
user message asks it to JUDGE from the transcript and, where it matters,
to re-check the disk — the phase is READ-ONLY: it has read/search tools
but cannot run commands or repair anything. It decides:
``verdict='done'`` stops the run, ``verdict='next_round'`` starts a new
plan/work cycle (always — no time or cycle cap; the hints for the next plan
ride along in ``state.results`` and are rendered by the next plan prompt). A
broken or missing deliverable is fixed by the next cycle, not here. Typed
output (``ReviewResult``: status/verdict/artifact/checks/hints/notes) via
the final_result tool; hard-capped by the fixed review cap (``budget.py``,
the runner enforces it, ``time`` omitted in config). Never retried on
error; a context-limit breach in the resumed history is recovered by
re-running the review on a truncated tail (``keep_recent``, see
runner._run_phase_with_retries).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from shlepa_agent.outputs import ReviewResult, output_schema_note
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


def keep_recent(messages: list[Any], n: int) -> list[Any]:
    """Keep only the most recent ``n`` messages of a conversation.

    Used by the terminal review's context-breach recovery (the runner
    re-runs the review on a progressively smaller tail). Drops dangling
    leading pieces so the result stays a valid history: a leading
    ModelRequest carrying tool returns whose matching tool calls were
    truncated away would 400 on the endpoint.
    """
    msgs = list(messages)[-max(n, 0):]
    while (
        msgs
        and isinstance(msgs[0], ModelRequest)
        and any(isinstance(p, ToolReturnPart) for p in msgs[0].parts)
    ):
        msgs.pop(0)
    return msgs


class CommitPhase(Phase):
    """Read-only reviewer: judges done vs next_round from the transcript
    and targeted read/search re-checks."""

    id = "commit"
    output_type = ReviewResult
    terminal = True

    def history(self, state: RunState) -> list[Any] | None:
        return trim_history(state.model.last_messages)

    def prompt(self, state: RunState) -> str:
        # The task is already in the system message (and in the resumed
        # history), so the user message carries the phase instructions, the
        # budget note and the ReviewResult schema.
        return render_user(
            state.cfg,
            self.id,
            {
                "phase_prompt": load_prompt(f"{self.id}.md"),
                "extra": self.limits_note(state),
                "output_schema": output_schema_note(ReviewResult),
            },
        )
