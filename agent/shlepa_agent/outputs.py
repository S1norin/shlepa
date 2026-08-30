"""Structured phase outputs for the 4-phase pipeline.

The plan and work phases end with a typed result (pydantic-ai output tool
``final_result``); these models are the machine-readable hand-off between
phases. Commit and emergency stay free text — they write the deliverable.
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
            "Ordered concrete actions for the work phase (commands, file "
            "operations, checks). Specific enough to execute without "
            "inventing new approaches."
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
    decision: Literal["commit", "replan"] = Field(
        description=(
            "'commit' — the deliverable is ready (or best-effort ready); "
            "'replan' — the plan itself was wrong or incomplete."
        )
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
