"""Structured phase outputs for the v5 pipeline (plan -> work -> review).

Every pipeline phase ends with a typed result (pydantic-ai output tool
``final_result``); these models are the machine-readable hand-off between
phases (and the structured contract of the run). The review (commit) phase
is the only terminal typed phase; the emergency phase (kept in code, unused
in v5) stays free text.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ArtifactSpec(BaseModel):
    """Structured deliverable spec extracted from the task instruction (v6).

    The harness mechanically checks the deliverable against this spec
    (exists / non_empty / parse_ok / keys_ok / valid — see
    ``deliverable_check.py``); it also feeds the REVIEW context packet,
    the salvage route and the best-at-exit snapshot.
    """

    kind: Literal["file", "test_command", "answer"] = Field(
        default="file",
        description=(
            "'file' — the task output is a file to write; 'test_command' — the "
            "deliverable is a patched program/repo validated by a test command; "
            "'answer' — the task output is a short value (flag, number, string)."
        ),
    )
    path: str = Field(
        default="",
        description="Deliverable file path as stated in the instruction (empty if none stated).",
    )
    format: str = Field(
        default="",
        description=(
            "json | csv | patch | text, only when stated in the instruction "
            "(empty if unstated)."
        ),
    )
    keys: list[str] = Field(
        default_factory=list,
        description=(
            "Top-level JSON keys or CSV columns required by the instruction "
            "(empty if none required)."
        ),
    )
    expected_content: str | None = Field(
        default=None,
        description=(
            "The full expected file content QUOTED VERBATIM, only when the "
            "instruction literally spells it out (e.g. 'the file must contain "
            "hello'). Never paraphrase, never guess — null unless the "
            "instruction states the content explicitly."
        ),
    )

    @field_validator("keys", mode="before")
    @classmethod
    def _coerce_keys_to_list(cls, value: Any) -> Any:
        # A stray scalar must not crash the plan (models do this).
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


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
    artifact_spec: ArtifactSpec = Field(
        default_factory=ArtifactSpec,
        description=(
            "Structured version of goal: the exact deliverable spec extracted "
            "from the instruction (kind/path/format/keys/expected_content). "
            "The harness mechanically checks the deliverable against it."
        ),
    )
    # v6: the former `decision` field (work|commit) is gone — the pipeline is
    # strictly linear (every plan flows to WORK), so the plan carries no
    # routing decision.


class PartialHandoff(BaseModel):
    """Typed hand-off for the plan-timeout final_ask (v6).

    When the plan phase is cut off by its cap, one tool-less final_ask asks
    the model to summarize what is already known. The work phase starts
    fresh and receives this JSON (plus the harness's deterministic
    LAST_TOOLS block) instead of the full plan transcript. Every field has
    a default so a weak or partial answer still validates; list fields
    also coerce a stray scalar into a one-element list.
    """

    objective: str = Field(
        default="",
        description=(
            "The deliverable objective as understood so far: file path, "
            "format, required fields/values (empty if not yet clear)."
        ),
    )
    findings: list[str] = Field(
        default_factory=list,
        description=(
            "Key facts already established, each with its evidence "
            "location (file, endpoint, tool output)."
        ),
    )
    files_seen: list[str] = Field(
        default_factory=list,
        description="Paths of the task files already inspected.",
    )
    hypotheses: list[str] = Field(
        default_factory=list,
        description="Working hypotheses about the solution (unverified).",
    )
    failed_paths: list[str] = Field(
        default_factory=list,
        description=(
            "Approaches/probes already tried and rejected, with the reason — "
            "so the work phase does not repeat them."
        ),
    )
    next_action: str = Field(
        default="",
        description=(
            "The single most valuable next action for the work phase."
        ),
    )
    deliverable_path_if_known: str = Field(
        default="",
        description="Deliverable path if already determined (empty otherwise).",
    )

    @field_validator(
        "findings", "files_seen", "hypotheses", "failed_paths", mode="before"
    )
    @classmethod
    def _coerce_to_list(cls, value: Any) -> Any:
        # Models frequently answer a list field with a bare string; a stray
        # scalar must not crash the hand-off.
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return value


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

    The review phase (phase id ``commit``) verifies — and, when needed,
    repairs — the deliverable with full tools, then decides the run:
    ``verdict='done'`` stops the run, ``verdict='next_round'`` starts a new
    plan/work cycle (always — there is no time or cycle cap).
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
            "Each mechanical check run and its outcome, e.g. "
            "'jq . /app/out.json -> valid'. Empty if nothing was checked."
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
