"""Salvage phase: write-only rescue when WORK left the deliverable absent.

Triggered by the runner after WORK when the mechanical check
(``deliverable_check.py``) finds the deliverable missing or empty on disk
and the kill-switch (``SHLEPA_SALVAGE``) is off-default-on. Fresh
context, one tool (write), 30 s explicit cap. The model writes the
deliverable from whatever it can state and ALWAYS mirrors the full
content into ``final_result.body``; the harness persists that body
atomically (runner.py) if the file is still missing/empty after the run.

Design: docs/plans/agent-v6-review-redesign.md, decision D1.
"""

from __future__ import annotations

from typing import Any

from shlepa_agent.outputs import SalvageResult, output_schema_note
from shlepa_agent.phases.base import Phase, RunState
from shlepa_agent.template import load_prompt, render_user


class SalvagePhase(Phase):
    id = "salvage"
    output_type = SalvageResult
    terminal = False

    def prompt(self, state: RunState) -> str:
        cfg = state.cfg
        spec: dict[str, Any] = state.deliverable_spec or {}
        check: dict[str, Any] = state.deliverable_check or {}
        reason = "missing" if not check.get("exists") else "empty"

        spec_lines = [
            f"kind: {spec.get('kind') or 'file'}",
            f"path: {spec.get('path') or '(not named)'}",
        ]
        if spec.get("format"):
            spec_lines.append(f"format: {spec['format']}")
        keys = spec.get("keys") or []
        if keys:
            spec_lines.append(
                "required top-level keys/columns: " + ", ".join(str(k) for k in keys)
            )
        if spec.get("expected_content") is not None:
            spec_lines.append(
                "expected_content (verbatim from the instruction):\n"
                + str(spec["expected_content"])
            )

        parts = [
            "DELIVERABLE SPEC (from the plan):\n" + "\n".join(spec_lines),
            "MECHANICAL CHECK AFTER WORK: the deliverable is "
            f"{reason} on disk ({check.get('reason') or 'no path'}).",
        ]
        plan = state.results.get("plan")
        if plan is not None and plan.output is not None:
            out = plan.output
            goal = getattr(out, "goal", None)
            findings = getattr(out, "findings", None)
            if goal is None and isinstance(out, dict):
                goal = out.get("goal")
                findings = out.get("findings")
            if goal or findings:
                parts.append(
                    "RECOVERABLE TEXT (plan):\n"
                    f"goal: {goal or ''}\nfindings: {findings or ''}"
                )
        work = state.results.get("work")
        if work is not None and work.output is not None:
            out = work.output
            summary = getattr(out, "summary", None)
            if summary is None and isinstance(out, dict):
                summary = out.get("summary")
            if summary:
                parts.append(f"RECOVERABLE TEXT (work):\n{summary}")

        return render_user(
            cfg,
            self.id,
            {
                "phase_prompt": load_prompt("salvage.md"),
                "extra": self.limits_note(state),
                "previous_results": "\n\n".join(parts),
                "output_schema": output_schema_note(SalvageResult),
            },
        )

    def history(self, state: RunState) -> list[Any] | None:
        return None  # fresh context by design (w2-3)
