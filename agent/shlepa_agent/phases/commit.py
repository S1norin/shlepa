"""Review phase (phase id ``commit``): read-only verifier (v6, w2-4).

The terminal phase verifies the deliverable and decides: ``verdict='done'``
ends the run, ``verdict='next_round'`` starts a new plan/work cycle (the
hints ride along in ``state.results`` and are rendered by the next plan
prompt). It is READ-ONLY (``read``/``search``; no bash/write/edit — repair
is a separate bounded phase, w2-5) and runs on a FRESH conversation built
from a harness packet (artifact spec + preloaded artifact + mechanical
check + decision summary + compact LAST_TOOLS), not from the work
transcript. ``SHLEPA_REVIEW_CTX=full`` restores the v5 behaviour (resume
the trimmed work conversation, old prompt) for A/B arms.

Typed output (``ReviewResult``: status/verdict/artifact/checks/hints/notes)
via the final_result tool; hard-capped by the fixed review cap (``budget.py``,
the runner enforces it, ``time`` omitted in config). Never retried.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, ToolCallPart, ToolReturnPart

from shlepa_agent.outputs import ReviewResult, output_schema_note
from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.state import extract_last_tools, render_last_tools
from shlepa_agent.template import load_prompt, render_user

#: Max characters of artifact content preloaded into the verify packet.
ARTIFACT_CAP = 8000
#: Max characters per decision-summary field (summary/findings/goal).
SUMMARY_CAP = 2000


def review_ctx_mode() -> str:
    """A/B knob: 'fresh' (default, v6 packet) or 'full' (v5 resumed history)."""
    return os.environ.get("SHLEPA_REVIEW_CTX", "fresh").strip().lower() or "fresh"


def _cap_text(text: str, cap: int = SUMMARY_CAP) -> str:
    text = (text or "").strip()
    if len(text) > cap:
        return text[:cap] + " [...TRUNCATED...]"
    return text


def _artifact_block(state: RunState) -> str:
    """Preload the artifact content (harness-side file read, capped)."""
    spec = state.deliverable_spec
    if not spec or not spec.get("path"):
        return "artifact: no path known — the deliverable could not be preloaded"
    kind = spec.get("kind") or "file"
    if kind == "test_command":
        return (
            f"deliverable kind=test_command: {spec['path']!r} — correctness is judged by "
            "running that command; the harness has NOT run it for you"
        )
    if kind == "answer":
        note = "deliverable kind=answer: judge against the instruction text and the spec above"
        if spec.get("expected_content"):
            note += (
                "\nexpected content (quoted from the instruction): "
                f"{spec['expected_content']!r}"
            )
        return note
    path = Path(spec["path"])
    if not path.is_absolute():
        path = state.deps.workdir / path
    if not path.is_file() or path.stat().st_size == 0:
        return "artifact: MISSING OR EMPTY on disk (the harness could not preload it)"
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"artifact: unreadable ({e})"
    if len(raw) > ARTIFACT_CAP:
        raw = raw[:ARTIFACT_CAP] + "\n[...TRUNCATED BY HARNESS...]"
    return "artifact content (preloaded by the harness):\n" + raw


def _check_block(state: RunState) -> str:
    check = state.deliverable_check
    if not check:
        return "mechanical check: not run (no path known or the gate was off)"
    return "mechanical check (harness, after WORK/SALVAGE): " + json.dumps(check)


def _summary_block(state: RunState) -> str:
    """Decision/evidence summary: what the model claimed before the review."""
    parts: list[str] = []
    work = state.results.get("work")
    if work is not None and work.output is not None:
        out = work.output
        summary = getattr(out, "summary", "") or ""
        findings = getattr(out, "findings", "") or ""
        if not summary and isinstance(out, dict):
            summary = out.get("summary") or ""
            findings = out.get("findings") or ""
        parts.append(
            "WORK summary: " + (_cap_text(summary) or "(empty)")
            + "\nWORK findings: " + (_cap_text(findings) or "(empty)")
        )
    plan = state.results.get("plan")
    if plan is not None and plan.output is not None:
        out = plan.output
        goal = getattr(out, "goal", "") or ""
        findings = getattr(out, "findings", "") or ""
        if not goal and isinstance(out, dict):
            goal = out.get("goal") or ""
            findings = out.get("findings") or ""
        if goal:
            parts.append("PLAN goal: " + _cap_text(goal))
        if findings:
            parts.append("PLAN findings: " + _cap_text(findings))
    last = state.results.get("commit")
    if last is not None and last.output is not None:
        hints = getattr(last.output, "hints", []) or []
        if hints:
            parts.append("previous round hints: " + "; ".join(str(h) for h in hints))
    if not parts:
        parts.append("(no decision summary available — plan/work left no typed output)")
    return "decision summary (what the model claimed):\n" + "\n".join(parts)


def _last_tools_block(state: RunState) -> str:
    entries = extract_last_tools(state.model.last_messages)
    rendered = render_last_tools(entries)
    return rendered.strip() if rendered else "(no tool activity recorded)"


def build_verify_packet(state: RunState) -> str:
    """Assemble the fresh-context packet for the read-only verifier."""
    spec = state.deliverable_spec
    lines = ["VERIFY PACKET (assembled by the harness — trust it over memory):"]
    if spec:
        line = (
            f"deliverable spec: kind={spec.get('kind')!r} path={spec.get('path')!r} "
            f"format={spec.get('format')!r} keys={spec.get('keys')!r}"
        )
        if spec.get("expected_content"):
            line += f" expected_content={spec['expected_content']!r}"
        lines.append(line)
    else:
        lines.append("deliverable spec: unknown (neither PLAN nor WORK named a path)")
    lines.append("")
    lines.append(_artifact_block(state))
    lines.append("")
    lines.append(_check_block(state))
    lines.append("")
    lines.append(_summary_block(state))
    lines.append("")
    lines.append("last tool activity before the review:")
    lines.append(_last_tools_block(state))
    return "\n".join(lines)


def trim_history(messages: list[Any]) -> list[Any]:
    """Build a safe message history for a continuation run (v5 mode).

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
    """Read-only verifier: checks the deliverable, decides done vs next_round."""

    id = "commit"
    output_type = ReviewResult
    terminal = True

    def history(self, state: RunState) -> list[Any] | None:
        if review_ctx_mode() == "full":
            return trim_history(state.model.last_messages)
        return None  # v6: fresh conversation, packet in the user message

    def prompt(self, state: RunState) -> str:
        if review_ctx_mode() == "full":
            # v5 shape: phase text + budget note + schema, on the resumed
            # work transcript.
            return render_user(
                state.cfg,
                self.id,
                {
                    "phase_prompt": load_prompt(f"{self.id}.md"),
                    "extra": self.limits_note(state),
                    "output_schema": output_schema_note(ReviewResult),
                },
            )
        # v6: fresh context; the packet carries everything the verifier needs.
        return render_user(
            state.cfg,
            self.id,
            {
                "phase_prompt": load_prompt(f"{self.id}.md"),
                "extra": build_verify_packet(state) + "\n\n" + self.limits_note(state),
                "output_schema": output_schema_note(ReviewResult),
            },
        )
