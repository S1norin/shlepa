"""Structured phase outputs for the v5 pipeline (plan -> work -> review).

Every pipeline phase ends with a typed result (pydantic-ai output tool
``final_result``); these models are the machine-readable hand-off between
phases (and the structured contract of the run). The review (commit) phase
is the only terminal typed phase; the emergency phase (kept in code, unused
in v5) stays free text.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class PlanResult(BaseModel):
    """Structured output of the plan phase."""

    goal: str = Field(
        description=(
            "Exact deliverable spec: file path, format, required "
            "fields/values, constraints — as stated in the task."
        )
    )
    findings: str = Field(
        default="",
        description=(
            "Key facts about the environment/target the plan relies on "
            "(empty if none)."
        ),
    )
    steps: list[str] = Field(
        description=(
            "Ordered concrete actions for the work phase. Format each step as "
            "'action; verify: how to check it worked'. Specific enough to "
            "execute without inventing new approaches."
        ),
    )
    risks: str = Field(
        default="",
        description=(
            "Main risks that could break this plan (wrong assumption, missing "
            "information, time) and how the work phase should handle them. "
            "Empty if none."
        ),
    )
    decision: Literal["work", "commit"] = Field(
        default="work",
        description=(
            "'work' — execute the plan (ALWAYS the correct choice: only the "
            "work phase can write the deliverable, and the runner routes "
            "every plan to work). 'commit' is a legacy value: the runner "
            "treats it exactly like 'work'."
        )
    )


class WorkResult(BaseModel):
    """Structured output of the work phase."""

    summary: str = Field(
        description="What was done: actions taken and verification results."
    )
    findings: str = Field(
        default="",
        description="New facts not known at planning time (empty if none).",
    )
    deliverable: str = Field(
        default="",
        description=(
            "Path of the deliverable file written (empty if nothing was "
            "written)."
        ),
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "How sure you are (0-1) that the deliverable is complete and "
            "correct. Be honest: 1.0 only after a passing mechanical check."
        ),
    )


class ReviewResult(BaseModel):
    """Structured output of the terminal review phase (v5).

    The review phase (phase id ``commit``) is TOOLLESS: it judges the
    run from the transcript alone (it cannot read, run checks, or repair
    anything), then decides: ``verdict='done'`` stops the run,
    ``verdict='next_round'`` starts a new plan/work cycle (always — there
    is no time or cycle cap).
    """

    status: Literal["ok", "partial"] = Field(
        description=(
            "'ok' — the deliverable exists and ALL mechanical checks passed; "
            "'partial' — best-effort: something is missing, broken or "
            "unchecked."
        )
    )
    verdict: Literal["done", "next_round"] = Field(
        description=(
            "'done' — stop now with the current deliverable (best effort if "
            "partial); 'next_round' — a new plan/work round would materially "
            "improve the result."
        )
    )
    artifact: str = Field(
        description=(
            "Absolute path of the deliverable file (empty if none was "
            "written)."
        )
    )
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "Verification evidence OBSERVED IN THE TRANSCRIPT (this phase "
            "has no tools and runs nothing itself): the mechanical checks "
            "the work phase reported with their outcomes, e.g. 'work ran: "
            "jq . /app/out.json -> valid'. Empty if the transcript shows no "
            "checks."
        ),
    )
    hints: list[str] = Field(
        default_factory=list,
        description=(
            "For verdict='next_round' only: concrete hints for the next "
            "plan/work round — what was wrong and what must change. Empty "
            "for 'done'."
        ),
    )
    notes: str = Field(
        default="",
        description=(
            "One line: what the deliverable is (empty if self-evident)."
        ),
    )


def output_schema_note(model_cls: type[BaseModel]) -> str:
    """Render the 'output_schema' user-message block for a typed phase.

    Tells the model to finish via the ``final_result`` tool and shows the
    exact JSON schema it must match.
    """
    schema = model_cls.model_json_schema()
    return (
        "Finish by calling the final_result tool with a JSON object "
        "matching this schema:\n" + json.dumps(schema, indent=2)
    )
