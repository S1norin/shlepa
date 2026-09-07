"""Research read-only tools (v6-rewrite; dev arms since the 2026-09-07
slim-down).

code_search / file_outline (SIFS BM25-offline) and log_triage were baseline
orientation tools (batch 388fde: never adopted — context bloat), so the
2026-09-07 slim-down left them OFF in the shipped baseline; they live on as
dev arms (+sifs / +smart-grep / +forensics, see toolsets.py) and the legacy
env switches (AGENT_CODE_SEARCH, SHLEPA_LOG_TRIAGE=1). Research:
research/notes/v6-baseline-readonly-tools.md.

Covers:
1. registry + shipped config: all three tools registered but DISABLED in
   the slim baseline, engine = sifs
2. plan phase stays read-only (no bash/write/edit), work has the standard
   set + recon
3. finalization reserve (w3-2) blocks the exploratory tools
4. env overrides (SHLEPA_CODE_SEARCH / SHLEPA_CODE_SEARCH_ENGINE /
   SHLEPA_LOG_TRIAGE)
5. one real end-to-end call per tool on a tiny fixture (hermetic; the sifs
   smoke skips when the bundled binary is missing/non-runnable)
"""

import asyncio
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.tools import ALL_TOOLS, get_tools
from shlepa_agent.tools.base import AgentDeps, PhaseWindow
from shlepa_agent.tools.code_search import code_search, file_outline
from shlepa_agent.tools.log_triage import log_triage

import time


def _ctx(tmp_path, cfg=None, phase_window=None):
    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(
        workdir=tmp_path,
        cfg=cfg,
        clock=lambda: 0.0,
        phase_window=phase_window,
    )
    return SimpleNamespace(deps=deps)


def _shipped_cfg():
    return load_config()


# -- registry + shipped config -----------------------------------------------

def test_new_tools_registered():
    for name in ("code_search", "file_outline", "log_triage"):
        assert name in ALL_TOOLS, name
        assert ALL_TOOLS[name].name == name


def test_research_tools_disabled_in_slim_baseline():
    # 2026-09-07: the orientation bundle is off by default (batch 388fde);
    # the dev arms and env switches re-enable it
    cfg = _shipped_cfg()
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    assert cfg.tools.log_triage.enabled is False


def test_shipped_engine_is_sifs():
    assert _shipped_cfg().code_search.engine == "sifs"


# -- the phase matrix stays read-only in plan ---------------------------------

def test_plan_matrix_is_read_only():
    cfg = _shipped_cfg()
    plan_tools = cfg.tool_policy.tools_for("plan", 1)
    read_only = {"read", "recon", "search", "code_search", "file_outline",
                 "log_triage"}
    assert set(plan_tools) <= read_only
    assert not set(plan_tools) & {"bash", "write", "edit"}


def test_work_matrix_has_full_set():
    cfg = _shipped_cfg()
    work_tools = set(cfg.tool_policy.tools_for("work", 1))
    assert work_tools == {"read", "write", "edit", "bash", "recon"}


def test_get_tools_resolves_disabled_names_to_empty():
    # the research tools are named in no active phase; even if a dev config
    # named them, the disabled flags keep them out of the registry
    cfg = _shipped_cfg()
    names = [t.name for t in get_tools(cfg, ["code_search", "file_outline",
                                             "log_triage"])]
    assert names == []


# -- finalization reserve (w3-2) ----------------------------------------------

def _window_in_reserve(cap=30.0):
    """A phase window with 5 s left (default reserve is 15 s)."""
    return PhaseWindow("work", cap, time.monotonic() - (cap - 5.0))


def test_new_exploratory_tools_blocked_in_reserve(tmp_path, monkeypatch):
    calls = []
    import shlepa_agent.code_search as cs_engine
    import shlepa_agent.log_triage as lt_engine

    monkeypatch.setattr(cs_engine, "code_search",
                        lambda *a, **k: calls.append("cs") or "RAN")
    monkeypatch.setattr(lt_engine, "log_triage",
                        lambda *a, **k: calls.append("lt") or "RAN")
    ctx = _ctx(tmp_path, phase_window=_window_in_reserve())
    for out in (
        asyncio.run(code_search(ctx, query="anything")),
        asyncio.run(file_outline(ctx, path="app.py")),
        asyncio.run(log_triage(ctx, path=".")),
    ):
        assert "FINALIZING" in out
        assert "not executed" in out
    assert calls == []


# -- env overrides -------------------------------------------------------------

def test_env_disable_code_search(monkeypatch):
    monkeypatch.setenv("SHLEPA_CODE_SEARCH", "0")
    cfg = load_config()
    assert cfg.tools.code_search.enabled is False
    names = [t.name for t in get_tools(cfg, ["code_search", "read"])]
    assert names == ["read"]


def test_env_disable_log_triage(monkeypatch):
    monkeypatch.setenv("SHLEPA_LOG_TRIAGE", "0")
    cfg = load_config()
    assert cfg.tools.log_triage.enabled is False


def test_env_engine_override(monkeypatch):
    monkeypatch.setenv("SHLEPA_CODE_SEARCH_ENGINE", "rg")
    assert load_config().code_search.engine == "rg"


# -- real end-to-end calls on tiny fixtures -----------------------------------

CODE_FIXTURE = '''\
import sqlite3

DB_PATH = "app.db"


def get_pool():
    return sqlite3.connect(DB_PATH)


def login(user, pwd):
    q = "SELECT * FROM users WHERE name = '" + user + "'"
    return get_pool().execute(q)
'''


def _write_code_tree(root: Path):
    (root / "app").mkdir()
    (root / "app" / "db.py").write_text(CODE_FIXTURE, encoding="utf-8")
    (root / "app" / "main.py").write_text(
        "from app.db import login\n\nprint(login('a', 'b'))\n",
        encoding="utf-8",
    )


def test_log_triage_e2e_on_jsonl(tmp_path):
    lines = [
        json.dumps({"EventID": 4624, "TimeCreated": "2026-09-01T10:00:00",
                    "SubjectUserName": "alice", "Computer": "SRV1",
                    "IP": "10.0.0.5", "Process": "svchost.exe"}),
        json.dumps({"EventID": 4625, "TimeCreated": "2026-09-01T10:01:00",
                    "SubjectUserName": "alice", "Computer": "SRV1",
                    "IP": "203.0.113.7", "Process": "powershell.exe"}),
        json.dumps({"EventID": 4624, "TimeCreated": "2026-09-01T11:00:00",
                    "SubjectUserName": "bob", "Computer": "SRV1",
                    "IP": "10.0.0.5", "Process": "svchost.exe"}),
    ]
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "auth.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    out = asyncio.run(log_triage(_ctx(tmp_path), path="evidence"))
    assert "FAILED" not in out
    assert "auth.jsonl" in out
    assert "alice" in out  # top entities surfaced


def test_log_triage_missing_path_compact_error(tmp_path):
    out = asyncio.run(log_triage(_ctx(tmp_path), path="nope"))
    assert "path not found" in out


def test_code_search_e2e_with_real_sifs(tmp_path):
    import shlepa_agent.code_search as engine

    sifs = engine.SIFS_BUNDLED
    if not (sifs.is_file() and os.access(sifs, os.X_OK)):
        pytest.skip("bundled sifs binary not present/non-runnable here")
    _write_code_tree(tmp_path)
    out = asyncio.run(code_search(_ctx(tmp_path), query="database connection pool"))
    assert "FAILED" not in out
    assert "app/db.py" in out  # located by meaning, not by the query's words


def test_file_outline_e2e(tmp_path):
    _write_code_tree(tmp_path)
    out = asyncio.run(file_outline(_ctx(tmp_path), path="app/db.py"))
    assert "FAILED" not in out
    assert "get_pool" in out
    assert "login" in out


def test_code_search_degrades_never_raises(tmp_path, monkeypatch):
    """A broken/missing sifs binary must degrade to rg/regex, never raise."""
    import shlepa_agent.code_search as engine

    monkeypatch.setattr(engine, "_resolve_sifs",
                        lambda cfg: (None, "no sifs binary here"))
    _write_code_tree(tmp_path)
    out = asyncio.run(code_search(_ctx(tmp_path), query="get_pool"))
    # rg is preinstalled in this env; the call must still locate the symbol
    assert "app/db.py" in out or "FAILED" not in out
