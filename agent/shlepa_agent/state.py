"""Compact run-state file (`.shlepa_state.json`) in the working directory.

Written after every phase (and at run start) so that a run can be analyzed
after the fact without the LLM trace: the derived budget, cycle count, and
each phase's structured outcome (status, summary, deliverable, error).

The file is dev/trace convenience only — the agent never reads it back.
Failures to write it are swallowed (a broken state file must never affect
the run).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from shlepa_agent.budget import Budget
from shlepa_agent.phases.base import RunState

STATE_FILENAME = ".shlepa_state.json"


def save_state(state: RunState, budget: Budget | None = None) -> None:
    """Atomically (re)write the run-state file in the working directory."""
    try:
        budget = budget if budget is not None else state.deps.budget
        data = {
            "elapsed": round(state.model.elapsed(), 1),
            "cycles": state.cycles,
            "budget": asdict(budget) if budget is not None else None,
            "results": {
                phase_id: {
                    "status": res.status,
                    "summary": (res.summary or "")[:4000],
                    "deliverable": res.deliverable,
                    "error": res.error,
                }
                for phase_id, res in state.results.items()
            },
        }
        target = state.deps.workdir / STATE_FILENAME
        tmp = state.deps.workdir / (STATE_FILENAME + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, default=str)
        os.replace(tmp, target)
    except OSError:
        pass  # never let state-file IO affect the run
