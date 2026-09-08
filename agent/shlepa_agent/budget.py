"""Fixed time regime (v5) — no per-task horizon.

The agent works in plan/work/review cycles and stops when the review
verdict is "done" (or on an unrecoverable error). There is NO task time
limit T, NO global hard wall-clock stop and NO request-start gate inside
the agent: the container itself is killed at the task's own limit, and the
work phase keeps the deliverable file fresh on disk, so whatever exists at
kill time is what scores. The only bounds are the per-operation ones
below.

Regime (seconds) — fixed constants, no per-task derivation:

    plan     = PLAN_CAP   (80)  plan phase cap
    work     = WORK_CAP   (120) work phase cap per cycle
    review   = REVIEW_CAP (60)  review (commit) phase cap (read-only
                                disk verification: a few read/search
                                round trips per check)
    bash     = BASH_MAX   (30)  bash per-call cap (also the tool max)
    llm wall = LLM_WALL   (180) per-request wall-clock cap (open -> last
                                chunk)

There is NO token budget and NO request-count limit: token usage is still
logged per request (telemetry / tie-break analysis) but never enforced.
Pure stdlib; no agent-specific imports.
"""
from __future__ import annotations

PLAN_CAP = 80.0
WORK_CAP = 120.0
REVIEW_CAP = 60.0
BASH_MAX = 30.0
LLM_WALL = 180.0

#: One full plan + work + review cycle at the regime caps.
FULL_CYCLE = PLAN_CAP + WORK_CAP + REVIEW_CAP


def regime() -> dict[str, float]:
    """Snapshot of the fixed regime for logs and the state file."""
    return {
        "plan": PLAN_CAP,
        "work": WORK_CAP,
        "review": REVIEW_CAP,
        "bash": BASH_MAX,
        "llm_wall": LLM_WALL,
    }
