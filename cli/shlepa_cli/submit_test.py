"""shlepa submit-test: strict contest-faithful test via Harbor.

Builds the submission zip (telemetry stripped), unzips it, and runs
Harbor (harbor==0.16.1, already a cli dependency) against the selected
tasks using the unzipped agent. The agent executes inside the acp
container exactly as in the contest; telemetry is off by construction
because the telemetry package is absent from the zip.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class HarborTrial:
    """One parsed Harbor trial."""

    task_name: str
    status: str  # "solved" | "unsolved" | "timeout" | "error"
    reward: float | None
    tokens_in: int | None
    tokens_out: int | None
    duration_sec: float | None
    error: str | None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_job_result(path: Path) -> list[HarborTrial]:
    """Parse a Harbor ``result.json`` into a list of :class:`HarborTrial`.

    A trial is *solved* when its verifier reward equals 1 and no
    exception was raised. A raised exception maps to ``timeout`` (when the
    exception type is a timeout) or ``error`` otherwise.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Harbor result not found: {path}")
    data = json.loads(path.read_text())
    trials: list[HarborTrial] = []
    for raw in data.get("trial_results", []):
        exception = raw.get("exception_info")
        error: str | None = None
        status: str | None = None
        if exception is not None:
            etype = exception.get("exception_type", "Exception")
            emsg = exception.get("exception_message", "")
            error = f"{etype}: {emsg}"
            status = "timeout" if "Timeout" in etype else "error"

        verifier = raw.get("verifier_result") or {}
        rewards = verifier.get("rewards")
        reward: float | None = None
        if isinstance(rewards, dict):
            value = rewards.get("reward")
            reward = float(value) if isinstance(value, (int, float)) else None

        if status is None:
            status = "solved" if reward == 1 else "unsolved"

        agent_result = raw.get("agent_result") or {}
        started = _parse_ts(raw.get("started_at"))
        finished = _parse_ts(raw.get("finished_at"))
        duration: float | None = None
        if started is not None and finished is not None:
            duration = (finished - started).total_seconds()

        trials.append(
            HarborTrial(
                task_name=raw.get("task_name") or raw.get("trial_name", ""),
                status=status,
                reward=reward,
                tokens_in=agent_result.get("n_input_tokens"),
                tokens_out=agent_result.get("n_output_tokens"),
                duration_sec=duration,
                error=error,
            )
        )
    return trials
