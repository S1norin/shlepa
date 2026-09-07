"""Tests for the fixed time regime (shlepa_agent.budget, v5).

There is NO task time limit T, NO hard stop, NO margin, NO gate: the regime
is a set of fixed per-operation constants.
"""
from __future__ import annotations

from shlepa_agent.budget import (
    BASH_MAX,
    FULL_CYCLE,
    LLM_WALL,
    PLAN_CAP,
    REVIEW_CAP,
    WORK_CAP,
    regime,
)


def test_regime_constants():
    # v6: the plan cap dropped 60 -> 30 (read-only recon + search are cheap;
    # the old 60s cap was burned on recon+scratch before any real plan).
    assert PLAN_CAP == 30.0
    assert WORK_CAP == 120.0
    assert REVIEW_CAP == 45.0
    assert BASH_MAX == 30.0
    assert LLM_WALL == 180.0


def test_full_cycle():
    assert FULL_CYCLE == PLAN_CAP + WORK_CAP + REVIEW_CAP
    assert FULL_CYCLE == 195.0


def test_regime_snapshot():
    assert regime() == {
        "plan": 30.0,
        "work": 120.0,
        "review": 45.0,
        # w2-6: review-stage subcaps (VERIFY/REPAIR/decide), summing to the
        # 45 s envelope.
        "review_subcap_verify": 15.0,
        "review_subcap_repair": 20.0,
        "review_subcap_decide": 10.0,
        "bash": 30.0,
        "llm_wall": 180.0,
        # w3-2: finalization reserve (last R s of a phase cap ->
        # exploratory tools disabled).
        "finalize_reserve": 15.0,  # v6-rewrite: widened from 10 s
    }
