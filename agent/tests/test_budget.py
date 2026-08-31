"""Tests for the fixed per-task time regime (shlepa_agent.budget, v5)."""
from __future__ import annotations

import pytest

from shlepa_agent.budget import (
    BASH_MAX,
    LLM_WALL,
    MARGIN,
    PLAN_CAP,
    REVIEW_CAP,
    T_FALLBACK,
    T_MIN,
    TIME_ENV_CANDIDATES,
    WORK_CAP,
    derive_budget,
    extract_time_limit,
)


@pytest.mark.parametrize("t", [60, 120, 200, 300, 600, 900, 1500])
def test_fixed_regime(t):
    b = derive_budget(t)
    # Caps are constants — they do not depend on T.
    assert b.plan == PLAN_CAP
    assert b.work == WORK_CAP
    assert b.review == REVIEW_CAP
    assert b.bash_cap == BASH_MAX
    assert b.llm_wall == LLM_WALL
    assert b.margin == MARGIN
    # Only the hard stop follows T.
    assert b.T == max(T_MIN, float(t))
    assert b.hard == b.T - MARGIN
    assert b.gate_min == MARGIN + 5.0


def test_t_min_clamp():
    b = derive_budget(30)
    assert b.T == T_MIN
    assert b.hard == T_MIN - MARGIN


def test_full_cycle_constants():
    b = derive_budget(600.0)
    assert b.plan + b.work + b.review == 225.0
    # A 600s task (hard 585s) still fits several full cycles.
    assert b.hard >= 2 * (b.plan + b.work + b.review)


def test_short_task_single_cycle():
    # A 120s task (hard 105s) cannot fit a full 225s cycle: the runner
    # enters work directly and the reviewer decides done/next_round.
    b = derive_budget(120.0)
    assert b.hard < b.plan + b.work + b.review


def test_describe_reports_fixed_regime():
    text = derive_budget(600.0).describe()
    assert "no token/request limits" in text
    assert "source=" in text


def _clear_limit_env(monkeypatch):
    for key in TIME_ENV_CANDIDATES + ("TASK_DIR",):
        monkeypatch.delenv(key, raising=False)


def test_extract_time_env_wins(monkeypatch):
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv("TASK_TIMEOUT_SEC", "420")
    value, source = extract_time_limit("You have 10 minutes to finish the task.")
    assert value == 420.0
    assert source.startswith("env:")


def test_extract_time_slepa_agent_timeout(monkeypatch):
    # The dev engine (cli run) passes the task timeout_sec to the agent
    # container as SLEPA_AGENT_TIMEOUT — it must be the first source.
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv("SLEPA_AGENT_TIMEOUT", "240.5")
    value, source = extract_time_limit("time limit: 60 seconds")
    assert value == 240.5
    assert source.startswith("env:SLEPA_AGENT_TIMEOUT")


def test_extract_time_from_toml(tmp_path, monkeypatch):
    _clear_limit_env(monkeypatch)
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.toml").write_text("[agent]\ntimeout_sec = 480.0\n")
    monkeypatch.setenv("TASK_DIR", str(task_dir))
    value, source = extract_time_limit("")
    assert value == 480.0
    assert source.startswith("toml:")


def test_extract_time_from_text(monkeypatch):
    _clear_limit_env(monkeypatch)
    value, source = extract_time_limit("You have 10 minutes to finish the task.")
    assert value == 600.0
    assert source == "text"
    value, source = extract_time_limit("Time limit: 90 seconds.")
    assert value == 90.0
    assert source == "text"


def test_extract_time_fallback(monkeypatch):
    _clear_limit_env(monkeypatch)
    value, source = extract_time_limit("No explicit limit is stated here.")
    assert value == T_FALLBACK
    assert source == "fallback"
