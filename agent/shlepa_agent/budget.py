"""Fixed time regime (v5) — no per-task horizon.

The agent works in plan/work/review cycles and stops when the review
verdict is "done" (or on an unrecoverable error). There is NO task time
limit T, NO global hard wall-clock stop and NO request-start gate inside
the agent: the container itself is killed at the task's own limit, and the
work phase keeps the deliverable file fresh on disk, so whatever exists at
kill time is what scores. The only bounds are the per-operation ones
below.

Regime (seconds) — fixed constants, no per-task derivation:

    plan     = PLAN_CAP   (30)  plan phase cap (v6: read-only recon is
                                cheap; the 27B cohort was burning the old
                                60 s cap on recon+scratch work before any
                                real plan)
    work     = WORK_CAP   (120) work phase cap per cycle
    review   = REVIEW_CAP (45)  review-stage ENVELOPE (v6: the sum of the
                                subcaps below; SHLEPA_REVIEW_SUBCAPS=0
                                restores the v5 single 45 s request)
    review subcaps (v6, w2-6) — each an SEPARATE request, so the envelope
    kill can never catch "work + decide" in one in-flight stream:
        verify  = REVIEW_SUBCAP_VERIFY (15) VERIFY (commit phase) cap
        repair  = REVIEW_SUBCAP_REPAIR (20) REPAIR phase cap
        decide  = REVIEW_SUBCAP_DECIDE (10) harness decide after the
                                             repair re-check (no LLM
                                             request in the default wiring
                                             — the cap bounds the
                                             harness work)
    bash     = BASH_MAX   (30)  bash per-call cap (also the tool max)
    llm wall = LLM_WALL   (180) per-request wall-clock cap (open -> last
                                chunk)

There is NO token budget and NO request-count limit: token usage is still
logged per request (telemetry / tie-break analysis) but never enforced.
Pure stdlib; no agent-specific imports.
"""
from __future__ import annotations

import os

PLAN_CAP = 30.0
WORK_CAP = 120.0
REVIEW_CAP = 45.0  # review-stage envelope (v6: sum of the subcaps)
BASH_MAX = 30.0
LLM_WALL = 180.0
#: v6 (w3-2): finalization reserve — in the last R seconds of a phase cap
#: the exploratory tools (bash/search/recon) are disabled so the model
#: spends the window finalizing the deliverable instead of exploring.
FINALIZE_RESERVE = 15.0  # v6-rewrite: widened from 10 s (decision 2026-09-05)


def finalize_reserve() -> float:
    """w3-2: the reserve, honoring the SHLEPA_FINALIZE_RESERVE override
    (seconds; 0 disables the reserve)."""
    v = os.environ.get("SHLEPA_FINALIZE_RESERVE")
    if v is not None:
        try:
            return max(0.0, float(v))
        except ValueError:
            pass
    return FINALIZE_RESERVE


# v6 (w2-6) review-stage subcaps: VERIFY / REPAIR / decide each run as a
# separate request under the 45 s envelope, so the envelope kill can never
# catch "work + decide" in one in-flight stream.
REVIEW_SUBCAP_VERIFY = 15.0
REVIEW_SUBCAP_REPAIR = 20.0
REVIEW_SUBCAP_DECIDE = 10.0
assert (
    REVIEW_SUBCAP_VERIFY + REVIEW_SUBCAP_REPAIR + REVIEW_SUBCAP_DECIDE
    == REVIEW_CAP
)

#: One full plan + work + review cycle at the regime caps.
FULL_CYCLE = PLAN_CAP + WORK_CAP + REVIEW_CAP


def regime() -> dict[str, float]:
    """Snapshot of the fixed regime for logs and the state file."""
    return {
        "plan": PLAN_CAP,
        "work": WORK_CAP,
        "review": REVIEW_CAP,
        "review_subcap_verify": REVIEW_SUBCAP_VERIFY,
        "review_subcap_repair": REVIEW_SUBCAP_REPAIR,
        "review_subcap_decide": REVIEW_SUBCAP_DECIDE,
        "bash": BASH_MAX,
        "llm_wall": LLM_WALL,
        "finalize_reserve": finalize_reserve(),
    }
