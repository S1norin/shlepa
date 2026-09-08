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
    assert PLAN_CAP == 80.0
    assert WORK_CAP == 120.0
    assert REVIEW_CAP == 60.0
    assert BASH_MAX == 30.0
    assert LLM_WALL == 180.0


def test_full_cycle():
    assert FULL_CYCLE == PLAN_CAP + WORK_CAP + REVIEW_CAP
    assert FULL_CYCLE == 260.0


def test_regime_snapshot():
    assert regime() == {
        "plan": 80.0,
        "work": 120.0,
        "review": 60.0,
        "bash": 30.0,
        "llm_wall": 180.0,
    }
