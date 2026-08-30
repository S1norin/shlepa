"""Tests for the adaptive per-task budget (shlepa_agent.budget)."""
from __future__ import annotations

import pytest

from shlepa_agent.budget import (
    T_FALLBACK,
    T_MIN,
    TOKEN_ENV_CANDIDATES,
    TOKEN_FALLBACK,
    TOKEN_FRACTION,
    TIME_ENV_CANDIDATES,
    derive_budget,
    extract_token_limit,
    extract_time_limit,
)


@pytest.mark.parametrize(
    ("t", "hard", "reserve", "plan", "work", "cycles", "commit_cap", "bash_cap", "worst_commit"),
    [
        (60, 55.0, 0.0, 0.0, 25.0, 1, 45.0, 12.0, 30.0),
        (120, 115.0, 0.0, 30.0, 55.0, 1, 45.0, 24.0, 30.0),
        (150, 145.0, 0.0, 30.0, 85.0, 1, 45.0, 30.0, 30.0),
        (200, 194.0, 20.0, 45.0, 99.0, 1, 45.0, 40.0, 30.0),
        (300, 291.0, 30.0, 60.0, 171.0, 1, 60.0, 60.0, 30.0),
        (400, 388.0, 40.0, 60.0, 180.0, 1, 80.0, 80.0, 80.0),
        (500, 485.0, 50.0, 60.0, 180.0, 1, 100.0, 100.0, 100.0),
        (585, 570.0, 58.5, 60.0, 180.0, 2, 117.0, 117.0, 31.5),
        (600, 585.0, 60.0, 60.0, 180.0, 2, 120.0, 120.0, 45.0),
        (850, 835.0, 85.0, 60.0, 180.0, 3, 120.0, 170.0, 30.0),
        (900, 885.0, 90.0, 60.0, 180.0, 3, 120.0, 180.0, 75.0),
        (1095, 1080.0, 90.0, 60.0, 180.0, 4, 120.0, 219.0, 30.0),
        (1200, 1185.0, 90.0, 60.0, 180.0, 4, 120.0, 240.0, 120.0),
        (1500, 1485.0, 90.0, 60.0, 180.0, 5, 120.0, 240.0, 120.0),
    ],
)
def test_regime_table(
    t, hard, reserve, plan, work, cycles, commit_cap, bash_cap, worst_commit
):
    b = derive_budget(t)
    assert b.hard == pytest.approx(hard)
    assert b.reserve == pytest.approx(reserve)
    assert b.plan == pytest.approx(plan)
    assert b.work == pytest.approx(work)
    assert b.max_cycles == cycles
    assert b.commit_cap == pytest.approx(commit_cap)
    assert b.bash_cap == pytest.approx(bash_cap)
    assert min(b.commit_cap, b.commit_floor) == pytest.approx(worst_commit)


@pytest.mark.parametrize(
    "t", [60, 75, 90, 95, 110, 125, 150, 200, 250, 300, 350, 400, 450, 500,
          585, 600, 700, 850, 1000, 1200, 1500, 2000]
)
def test_invariants(t):
    b = derive_budget(t)
    assert b.T == max(T_MIN, float(t))
    assert b.hard < b.T
    assert 5.0 <= b.margin <= 15.0
    assert b.core == pytest.approx(b.hard - b.reserve)
    assert b.reserve == 0.0 or 20.0 <= b.reserve <= 90.0
    # no phase with less than 30s of allocation (plan off instead)
    assert b.plan == 0.0 or b.plan >= 30.0
    assert b.work > 0.0
    # plan + work must leave at least a 30s commit
    assert b.plan + b.work + 30.0 <= b.core + 1e-9
    assert b.max_cycles >= 1
    assert b.max_cycles * (b.plan + b.work) + 30.0 <= b.core + 1e-9
    assert b.commit_floor >= 30.0 - 1e-6
    assert b.commit_cap >= 45.0
    assert 10.0 <= b.bash_cap <= 240.0
    assert 5.0 <= b.finalize <= 20.0
    assert b.gate_min == pytest.approx(b.margin + 5.0)
    assert b.token_budget > 0


def test_plan_steps():
    assert derive_budget(60).plan == 0.0
    assert derive_budget(94).plan == 0.0  # core 89 < 90: plan does not fit
    assert derive_budget(95).plan == 30.0
    assert derive_budget(150).plan == 30.0
    assert derive_budget(199).plan == 30.0
    assert derive_budget(200).plan == 45.0
    assert derive_budget(299).plan == 45.0
    assert derive_budget(300).plan == 60.0
    assert derive_budget(600).plan == 60.0
    assert derive_budget(1500).plan == 60.0


def test_reserve_cut_below_20():
    assert derive_budget(60).reserve == 0.0
    assert derive_budget(120).reserve == 0.0
    assert derive_budget(199).reserve == 0.0
    assert derive_budget(200).reserve == pytest.approx(20.0)
    assert derive_budget(1500).reserve == 90.0  # capped


def test_token_budget_fraction():
    # 95% of the limit — including the fallback limit
    assert derive_budget(600).token_budget == int(TOKEN_FRACTION * TOKEN_FALLBACK)
    assert derive_budget(600, token_limit=500_000).token_budget == 475_000


def _clear_limit_env(monkeypatch):
    for key in TIME_ENV_CANDIDATES + TOKEN_ENV_CANDIDATES + ("TASK_DIR",):
        monkeypatch.delenv(key, raising=False)


def test_extract_time_env_wins(monkeypatch):
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv("TASK_TIMEOUT_SEC", "420")
    value, source = extract_time_limit("You have 10 minutes to finish the task.")
    assert value == 420.0
    assert source.startswith("env:")


def test_extract_time_slepa_agent_timeout(monkeypatch):
    # B6: the dev engine (cli run) passes the task timeout_sec to the agent
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


def test_extract_token_env(monkeypatch):
    _clear_limit_env(monkeypatch)
    monkeypatch.setenv("TOKEN_LIMIT", "500000")
    value, source = extract_token_limit("token budget 400000")
    assert value == 500_000.0
    assert source.startswith("env:")


def test_extract_token_text(monkeypatch):
    _clear_limit_env(monkeypatch)
    value, source = extract_token_limit("Your token budget is 400000 tokens.")
    assert value == 400_000.0
    assert source == "text"


def test_extract_token_fallback(monkeypatch):
    _clear_limit_env(monkeypatch)
    value, source = extract_token_limit("nothing to see")
    assert value == float(TOKEN_FALLBACK)
    assert source == "fallback"
