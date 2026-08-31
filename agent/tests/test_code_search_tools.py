"""Tests for the code_search/file_outline tool wiring (AGENT_CODE_SEARCH).

Two behaviors are under test:

- OFF (env unset): the agent is byte-identical to the baseline — the
  per-phase system prompts and registered tool names diff clean against
  the committed golden fixture (``fixtures/default_prompt.txt``, captured
  pre-wiring).
- ON (env = rg | sifs): both tools are registered in every phase, their
  usage notes render into the system prompt, and the engine follows the
  env value.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.runner import _system_prompt
from shlepa_agent.tools import get_tools

PHASES = ("plan", "work", "commit", "emergency")
TASK = "TASK"
FIXTURE = Path(__file__).parent / "fixtures" / "default_prompt.txt"


def _ctx(tmp_path, cfg=None, clock=None):
    cfg = cfg if cfg is not None else load_config()
    from shlepa_agent.tools.base import AgentDeps

    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=clock or (lambda: 0.0))
    return SimpleNamespace(deps=deps)


# ---------------------------------------------------------------------------
# golden baseline identity (env unset)
# ---------------------------------------------------------------------------


def _live_render(cfg) -> dict:
    out = {}
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        tools = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        out[phase_id] = (
            "tools: " + ", ".join(tools),
            _system_prompt(cfg, phase, TASK),
        )
    return out


def _fixture_sections() -> dict:
    text = FIXTURE.read_text(encoding="utf-8")
    idx = text.index("=== phase:")
    sections = {}
    for chunk in text[idx:].split("=== phase:")[1:]:
        lines = chunk.splitlines()
        phase_id = lines[0].strip()
        tools_line = lines[1]
        assert lines[2] == "--- prompt ---", phase_id
        sections[phase_id] = (tools_line, "\n".join(lines[3:]))
    return sections


def test_default_env_is_byte_identical_to_golden_baseline(monkeypatch):
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)
    live = _live_render(load_config())
    fixed = _fixture_sections()
    assert set(fixed) == set(PHASES)
    for phase_id in PHASES:
        tools_line, prompt = live[phase_id]
        f_tools, f_prompt = fixed[phase_id]
        assert tools_line == f_tools, f"{phase_id}: tool list diverged"
        assert prompt == f_prompt, (
            f"{phase_id}: system prompt diverged from the golden baseline"
        )


def test_env_invalid_value_stays_off(monkeypatch):
    for value in ("banana", "sifs-hybrid", ""):
        monkeypatch.setenv("AGENT_CODE_SEARCH", value)
        cfg = load_config()
        assert cfg.code_search.engine == "auto", value
        assert cfg.tools.code_search.enabled is False, value
        assert cfg.tools.file_outline.enabled is False, value
        assert set(cfg.phases["plan"].tools) == {"read", "write", "edit", "bash"}, value
        # full identity with the golden baseline too
        live = _live_render(cfg)
        fixed = _fixture_sections()
        for phase_id in PHASES:
            assert live[phase_id] == fixed[phase_id], (phase_id, value)


def test_env_value_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("AGENT_CODE_SEARCH", "SIFS")
    cfg = load_config()
    assert cfg.code_search.engine == "sifs"
    assert cfg.tools.code_search.enabled is True


def test_env_unset_leaves_config_untouched(monkeypatch):
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)
    cfg = load_config()
    assert cfg.code_search.engine == "auto"
    assert cfg.tools.code_search.enabled is False
    assert cfg.tools.file_outline.enabled is False
    for phase_id in PHASES:
        assert list(cfg.phases[phase_id].tools) == ["read", "write", "edit", "bash"]


# ---------------------------------------------------------------------------
# env enabled: tools + notes + engine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("engine", ["rg", "sifs"])
def test_env_registers_tools_and_notes_in_all_phases(monkeypatch, engine):
    monkeypatch.setenv("AGENT_CODE_SEARCH", engine)
    cfg = load_config()
    assert cfg.code_search.engine == engine
    assert cfg.tools.code_search.enabled is True
    assert cfg.tools.file_outline.enabled is True
    for phase_id in PHASES:
        phase = get_phase(phase_id)
        names = [t.name for t in get_tools(cfg, phase.tools(cfg))]
        assert names == ["read", "write", "edit", "bash", "code_search", "file_outline"]
        prompt = _system_prompt(cfg, phase, TASK)
        assert "code_search: search the codebase" in prompt
        assert "file_outline: list def/class/func symbols" in prompt


def test_code_search_timeout_env_override(monkeypatch):
    monkeypatch.setenv("SHLEPA_CODE_SEARCH_TIMEOUT", "12")
    cfg = load_config()
    assert cfg.tools.code_search.timeout == 12.0
    monkeypatch.setenv("SHLEPA_CODE_SEARCH_TIMEOUT", "not-a-number")
    assert load_config().tools.code_search.timeout == 30.0


# ---------------------------------------------------------------------------
# tool behavior (engine mapping, wall cap, result framing)
# ---------------------------------------------------------------------------


def test_code_search_tool_rg_real_engine(tmp_path, monkeypatch):
    import shlepa_agent.tools.code_search as tools_mod

    (tmp_path / "app.py").write_text(
        "def login(username):\n    return check(username)\n\n"
        "def check(x):\n    return x == 'admin'\n"
    )
    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg = load_config()
    out = asyncio.run(
        tools_mod.code_search(_ctx(tmp_path, cfg), query="admin")
    )
    assert out.startswith("[tool] code_search(")
    assert "UNTRUSTED TEXT ---------------" in out
    assert "END OF UNTRUSTED TEXT-----------" in out
    assert "app.py" in out
    assert "admin" in out


def test_code_search_tool_engine_mapping(monkeypatch, tmp_path):
    import shlepa_agent.code_search as engine_mod
    import shlepa_agent.tools.code_search as tools_mod

    calls: dict = {}

    def fake(query, path=".", **kwargs):
        calls["engine"] = kwargs.get("engine")
        return "ok-result"

    monkeypatch.setattr(engine_mod, "code_search", fake)

    monkeypatch.setenv("AGENT_CODE_SEARCH", "sifs")
    cfg = load_config()
    ctx = _ctx(tmp_path, cfg)
    asyncio.run(tools_mod.code_search(ctx, query="q", mode="bm25"))
    assert calls["engine"] == "sifs"
    asyncio.run(tools_mod.code_search(ctx, query="q", mode="hybrid"))
    assert calls["engine"] == "sifs-hybrid"

    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg_rg = load_config()
    ctx_rg = _ctx(tmp_path, cfg_rg)
    out = asyncio.run(tools_mod.code_search(ctx_rg, query="q", mode="hybrid"))
    assert calls["engine"] == "rg"
    assert "NOTE: hybrid mode needs the sifs engine" in out


def test_code_search_tool_wall_timeout(monkeypatch, tmp_path):
    import time

    import shlepa_agent.code_search as engine_mod
    import shlepa_agent.tools.code_search as tools_mod

    def slow(query, path=".", **kwargs):
        time.sleep(0.5)
        return "late"

    monkeypatch.setattr(engine_mod, "code_search", slow)
    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg = load_config()
    cfg.tools.code_search.timeout = 0.1
    out = asyncio.run(tools_mod.code_search(_ctx(tmp_path, cfg), query="q"))
    assert "timed out after 0.1s (per-call wall)" in out
    assert "UNTRUSTED TEXT ---------------" in out


def test_file_outline_tool_real_regex_engine(tmp_path, monkeypatch):
    import shlepa_agent.tools.code_search as tools_mod

    (tmp_path / "mod.py").write_text(
        "class Service:\n    def start(self):\n        pass\n\n"
        "def helper():\n    return 1\n"
    )
    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg = load_config()
    out = asyncio.run(tools_mod.file_outline(_ctx(tmp_path, cfg), path="mod.py"))
    assert out.startswith("[tool] file_outline(")
    assert "UNTRUSTED TEXT ---------------" in out
    assert "def start(self):" in out
    assert "def helper():" in out


def test_file_outline_tool_engine_mapping(monkeypatch, tmp_path):
    import shlepa_agent.code_search as engine_mod
    import shlepa_agent.tools.code_search as tools_mod

    calls: dict = {}

    def fake(path, workdir=None, **kwargs):
        calls["engine"] = kwargs.get("engine")
        return "outline-result"

    monkeypatch.setattr(engine_mod, "file_outline", fake)
    (tmp_path / "f.py").write_text("def a():\n    pass\n")

    monkeypatch.setenv("AGENT_CODE_SEARCH", "sifs")
    cfg = load_config()
    asyncio.run(tools_mod.file_outline(_ctx(tmp_path, cfg), path="f.py"))
    assert calls["engine"] == "sifs"

    monkeypatch.setenv("AGENT_CODE_SEARCH", "rg")
    cfg_rg = load_config()
    asyncio.run(tools_mod.file_outline(_ctx(tmp_path, cfg_rg), path="f.py"))
    assert calls["engine"] == "regex"
