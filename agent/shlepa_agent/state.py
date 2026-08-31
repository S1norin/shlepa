"""Compact run-state file for post-run analysis.

Written after every phase (and at run start) so that a run can be analyzed
after the fact without the LLM trace: the fixed regime, cycle count, and
each phase's structured outcome (status, summary, deliverable, error).

Location: $SHLEPA_STATE_FILE when set, else /tmp/shlepa_state.json — the
file is deliberately NOT written into the task workdir (the agent runs
inside contest containers; the workdir must stay clean for the grader).

The file is dev/trace convenience only — the agent never reads it back.
Failures to write it are swallowed (a broken state file must never affect
the run).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from shlepa_agent.budget import regime
from shlepa_agent.phases.base import RunState

STATE_FILENAME = "shlepa_state.json"
DEFAULT_STATE_PATH = Path("/tmp") / STATE_FILENAME


def _state_path() -> Path:
    """State-file location: $SHLEPA_STATE_FILE override, else /tmp default."""
    raw = os.environ.get("SHLEPA_STATE_FILE")
    if raw:
        return Path(raw)
    return DEFAULT_STATE_PATH


def save_state(state: RunState) -> None:
    """Atomically (re)write the run-state file (never into the workdir)."""
    try:
        data = {
            "elapsed": round(state.model.elapsed(), 1),
            "cycles": state.cycles,
            "regime": regime(),
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
        target = _state_path()
        tmp = Path(str(target) + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, default=str)
        os.replace(tmp, target)
    except OSError:
        pass  # never let state-file IO affect the run
