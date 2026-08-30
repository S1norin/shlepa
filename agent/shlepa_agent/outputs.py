"""Structured phase outputs for the 4-phase pipeline.

Every pipeline phase ends with a typed result (pydantic-ai output tool
``final_result``); these models are the machine-readable hand-off between
phases (and the structured contract of the run). Emergency stays free text —
it is the last-resort rescue, not a contract phase.
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
        description=(
            "'work' — execute the plan; 'commit' — the answer is already "
            "fully known, write the deliverable now."
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
    next_hints: list[str] = Field(
        default_factory=list,
        description=(
            "For decision='replan' only: concrete hints for the next plan — "
            "what was wrong and what must change. Ignored for 'commit'."
        ),
    )
    decision: Literal["commit", "replan"] = Field(
        description=(
            "'commit' — the deliverable is ready (or best-effort ready); "
            "'replan' — the plan itself was wrong or incomplete."
        )
    )


class CommitResult(BaseModel):
    """Structured output of the terminal commit phase."""

    status: Literal["ok", "partial", "unverified"] = Field(
        description=(
            "'ok' — the deliverable exists and ALL mechanical checks passed; "
            "'partial' — best-effort written, some checks failed or missing; "
            "'unverified' — written, but not checked."
        )
    )
    artifact: str = Field(
        description="Absolute path of the deliverable file."
    )
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "Each mechanical check run and its outcome, e.g. "
            "'jq . /app/out.json -> valid'. Empty if nothing was checked."
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
