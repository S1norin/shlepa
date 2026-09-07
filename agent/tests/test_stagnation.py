"""w3-4: stagnation Level A (shadow-only).

>=3 consecutive identical (tool key + adverse outcome) failures within
one phase log a ``stagnation`` shadow event. No blocking, no synthetic
result — the 474-trace replay found 0 strict candidates, enforcement
without a target is false-positive risk only.
"""

import json
import logging

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.state import stagnation_check
from shlepa_agent.tools.base import AgentDeps, PhaseWindow
from shlepa_agent.tools.bash import bash

import asyncio


@pytest.fixture
def events():
    from shlepa_agent.log import LOGGER

    records: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                records.append(json.loads(record.getMessage()))
            except (TypeError, ValueError):
                pass

    handler = _Collector()
    old_level = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        yield records
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(old_level)


def _ctx(tmp_path, phase_id="work"):
    deps = AgentDeps(
        workdir=tmp_path,
        cfg=load_config(),
        clock=lambda: 0.0,
        phase_window=PhaseWindow(phase_id, 30.0, __import__("time").monotonic()),
    )
    return type("C", (), {"deps": deps})(), deps


# -- stagnation_check unit tests ---------------------------------------------

def test_streak_threshold_and_counting():
    st: dict = {}
    assert stagnation_check(st, "work", "k") is None
    assert stagnation_check(st, "work", "k") is None
    assert stagnation_check(st, "work", "k") == 3
    assert stagnation_check(st, "work", "k") == 4


def test_different_key_breaks_streak():
    st: dict = {}
    stagnation_check(st, "work", "a")
    stagnation_check(st, "work", "a")
    assert stagnation_check(st, "work", "b") is None
    assert stagnation_check(st, "work", "b") is None
    assert stagnation_check(st, "work", "b") == 3


def test_phase_change_resets_streak():
    st: dict = {}
    stagnation_check(st, "work", "k")
    stagnation_check(st, "work", "k")
    assert stagnation_check(st, "plan", "k") is None  # new phase
    assert stagnation_check(st, "plan", "k") is None
    assert stagnation_check(st, "plan", "k") == 3


# -- tool-level: the event fires, behavior unchanged --------------------------

def _fail_bash(ctx, command="ls nothere"):
    out = asyncio.run(bash(ctx, command))
    return out


def test_third_identical_failure_logs_stagnation(tmp_path, events):
    ctx, deps = _ctx(tmp_path)
    _fail_bash(ctx)
    _fail_bash(ctx)
    assert not any(e.get("event") == "stagnation" for e in events)
    out3 = _fail_bash(ctx)
    st = [e for e in events if e.get("event") == "stagnation"]
    assert st, "the 3rd consecutive identical failure must log a shadow event"
    assert st[0]["phase"] == "work"
    assert st[0]["tool"] == "bash"
    assert st[0]["streak"] == 3
    assert "shadow only" in st[0]["note"]
    # behavior unchanged: the result is the usual (ledger-compressed) one
    assert "REPEATED FAILURE" in out3


def test_success_breaks_the_streak(tmp_path, events):
    ctx, deps = _ctx(tmp_path)
    _fail_bash(ctx)
    _fail_bash(ctx)
    asyncio.run(bash(ctx, "echo fine"))  # success breaks the streak
    _fail_bash(ctx, "ls other")  # different key anyway
    _fail_bash(ctx)
    _fail_bash(ctx)
    assert not any(e.get("event") == "stagnation" for e in events)


def test_phase_change_resets_at_tool_level(tmp_path, events):
    from dataclasses import replace

    import time as _t

    deps = AgentDeps(
        workdir=tmp_path,
        cfg=load_config(),
        clock=lambda: 0.0,
        phase_window=PhaseWindow("work", 30.0, _t.monotonic()),
    )
    ctx = type("C", (), {"deps": deps})()
    _fail_bash(ctx)
    _fail_bash(ctx)
    # same run continues in a new phase (the runner replaces the frozen
    # AgentDeps; the stagnation dict is shared by reference):
    deps2 = replace(deps, phase_window=PhaseWindow("plan", 30.0, _t.monotonic()))
    ctx2 = type("C", (), {"deps": deps2})()
    _fail_bash(ctx2)
    assert not any(e.get("event") == "stagnation" for e in events)
