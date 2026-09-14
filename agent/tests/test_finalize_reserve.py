"""w3-2: finalization reserve — last R s of a phase cap, deliverable
writes only.

Inside the reserve the exploratory tools (bash/recon) return a
synthetic FINALIZING result WITHOUT executing; write/edit/read keep
working. Default R = 10 s, override SHLEPA_FINALIZE_RESERVE (0 = off).
"""

import asyncio
import time

from shlepa_agent.config import load_config
from shlepa_agent.tools.base import AgentDeps, PhaseWindow
from shlepa_agent.tools.bash import bash
from shlepa_agent.tools.recon_tool import recon
from shlepa_agent.tools.write import write


def _deps(tmp_path, phase_window):
    return AgentDeps(
        workdir=tmp_path,
        cfg=load_config(),
        clock=lambda: 0.0,
        phase_window=phase_window,
    )


def _window_in_reserve(cap=30.0):
    """A phase window with 5 s left (default reserve is 10 s)."""
    return PhaseWindow("work", cap, time.monotonic() - (cap - 5.0))


def _window_fresh(cap=30.0):
    return PhaseWindow("work", cap, time.monotonic())


# -- the reserve window ------------------------------------------------------

def test_bash_blocked_in_reserve_not_executed(tmp_path):
    deps = _deps(tmp_path, _window_in_reserve())
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(bash(ctx, "touch marker && echo ran"))
    assert "FINALIZING" in out
    assert "not executed" in out
    assert "marker" not in str(out) or "[exit_code]" not in out
    assert not (tmp_path / "marker").exists()


def test_recon_blocked_in_reserve(tmp_path):
    deps = _deps(tmp_path, _window_in_reserve())
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(recon(ctx, mode="code", target="."))
    assert "FINALIZING" in out
    assert "not executed" in out


def test_write_allowed_in_reserve(tmp_path):
    deps = _deps(tmp_path, _window_in_reserve())
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(write(ctx, path="out.json", text='{"answer": 1}'))
    assert "FINALIZING" not in out
    assert (tmp_path / "out.json").read_text() == '{"answer": 1}'


# -- outside the reserve -----------------------------------------------------

def test_bash_executes_outside_reserve(tmp_path):
    deps = _deps(tmp_path, _window_fresh())
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(bash(ctx, "echo hello"))
    assert "FINALIZING" not in out
    assert "hello" in out


def test_no_window_is_inert(tmp_path):
    deps = _deps(tmp_path, None)
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(bash(ctx, "echo hi"))
    assert "FINALIZING" not in out
    assert "hi" in out


# -- knob --------------------------------------------------------------------

def test_reserve_env_override(tmp_path, monkeypatch):
    # 100 s reserve: even a fresh 30 s window is inside the reserve.
    monkeypatch.setenv("SHLEPA_FINALIZE_RESERVE", "100")
    deps = _deps(tmp_path, _window_fresh())
    ctx = type("C", (), {"deps": deps})()
    out = asyncio.run(bash(ctx, "touch m2"))
    assert "FINALIZING" in out
    assert not (tmp_path / "m2").exists()

    # 0 = disabled: inside the default window it executes.
    monkeypatch.setenv("SHLEPA_FINALIZE_RESERVE", "0")
    out = asyncio.run(bash(ctx, "echo ok2"))
    assert "FINALIZING" not in out
    assert "ok2" in out
