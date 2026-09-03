"""Tests for the recon tool (``shlepa_agent/tools/recon.py``).

The engine is covered in tests/test_recon.py (CLI parity, goldens, the
web deadline). Here the tool layer: registration (off by default, on
when enabled), output parity with the engine in data mode, the 30s
per-call wall against a hanging engine (issue #107), the max_output
cap and the SHLEPA_RECON_* env overrides.
"""

import asyncio
import json
import time
from types import SimpleNamespace

from shlepa_agent import recon as engine
from shlepa_agent.config import load_config
from shlepa_agent.phases import get_phase
from shlepa_agent.tools import get_tools
from shlepa_agent.tools.base import AgentDeps
import shlepa_agent.tools.recon as recon_tool

PHASES = ("plan", "work", "commit", "emergency")
BASE_TOOLS = ["read", "write", "edit", "bash"]


def _ctx(tmp_path, cfg=None):
    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=lambda: 0.0)
    return SimpleNamespace(deps=deps)


def _untrusted_body(out: str) -> str:
    """The body between the UNTRUSTED TEXT markers (the tool output)."""
    lines = out.splitlines()
    start = lines.index("UNTRUSTED TEXT ---------------")
    end = lines.index("END OF UNTRUSTED TEXT-----------")
    return "\n".join(lines[start + 1:end])


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_absent_by_default(monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)
    cfg = load_config()
    assert cfg.tools.recon.enabled is False
    for phase_id in PHASES:
        names = [t.name for t in get_tools(cfg, get_phase(phase_id).tools(cfg))]
        assert names == BASE_TOOLS  # recon not in the resolved list


def test_included_when_enabled():
    cfg = load_config()
    cfg.tools.recon.enabled = True
    tools = get_tools(cfg, BASE_TOOLS + ["recon"])
    assert [t.name for t in tools] == BASE_TOOLS + ["recon"]
    assert tools[-1].run is recon_tool.recon


# ---------------------------------------------------------------------------
# data-mode parity with the engine
# ---------------------------------------------------------------------------


def test_data_mode_parity_with_engine(tmp_path):
    """The tool body is the engine render, UNTRUSTED-wrapped, nothing else."""
    ev = tmp_path / "evidence"
    ev.mkdir()
    (ev / "notes.txt").write_text("case_id=IR-1\nflag{deadbeef}\n")
    lines = [
        json.dumps({"ts": f"2026-05-01T10:00:{i:02d}Z",
                    "event": "upload" if i % 2 else "login"})
        for i in range(10)
    ]
    (ev / "app.jsonl").write_text("\n".join(lines) + "\n")

    cfg = load_config()
    cfg.tools.recon.enabled = True
    out = asyncio.run(
        recon_tool.recon(_ctx(tmp_path, cfg), mode="data", target="evidence"))
    body = _untrusted_body(out)
    got = json.loads(body)

    want = json.loads(engine.render(engine.recon_data(ev)))
    got.pop("stats")  # volatile wall-clock stat, same convention as test_recon
    want.pop("stats")
    assert got == want
    # instrumented header + environment data markers
    assert out.splitlines()[0] == "[tool] recon(mode='data', target='evidence')"


# ---------------------------------------------------------------------------
# per-call wall
# ---------------------------------------------------------------------------


def test_hanging_target_hits_default_wall(tmp_path, monkeypatch):
    """AC: a hanging engine returns a timeout result in ~30s, never raising."""

    def slow(*args, **kwargs):
        time.sleep(31.0)
        return {}

    monkeypatch.setattr(engine, "recon_code", slow)
    cfg = load_config()
    cfg.tools.recon.enabled = True
    assert cfg.tools.recon.timeout == 30.0  # the default wall

    async def call():
        # measure inside the coroutine: asyncio.run joins the worker
        # thread at teardown, which is not part of the tool's wall
        t0 = time.monotonic()
        out = await recon_tool.recon(_ctx(tmp_path, cfg), mode="code", target="x")
        return out, time.monotonic() - t0

    out, wall = asyncio.run(call())
    assert "timed out after 30s" in out
    assert 29 <= wall < 32  # the wall actually bound, not an early exit


def test_wall_respects_config_timeout(tmp_path, monkeypatch):
    def slow(*args, **kwargs):
        time.sleep(2.0)
        return {}

    monkeypatch.setattr(engine, "recon_code", slow)
    cfg = load_config()
    cfg.tools.recon.enabled = True
    cfg.tools.recon.timeout = 0.3

    async def call():
        t0 = time.monotonic()
        out = await recon_tool.recon(_ctx(tmp_path, cfg), mode="code", target="x")
        return out, time.monotonic() - t0

    out, wall = asyncio.run(call())
    assert "timed out after 0.3s" in out
    assert wall < 1.0  # the shortened wall fired, not the 2s sleep


# ---------------------------------------------------------------------------
# output cap + env overrides
# ---------------------------------------------------------------------------


def test_max_output_cap(tmp_path, monkeypatch):
    # render() itself caps at 8192 bytes; a lower max_output caps harder
    monkeypatch.setattr(
        engine, "recon_data", lambda root: {"errors": ["e" * 2000] * 10})
    cfg = load_config()
    cfg.tools.recon.enabled = True
    cfg.tools.recon.max_output = 1000

    out = asyncio.run(
        recon_tool.recon(_ctx(tmp_path, cfg), mode="data", target="."))
    assert len(_untrusted_body(out)) <= 1000
    assert any("truncated to 1000 chars (tools.recon.max_output)" in ln
               for ln in out.splitlines())


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SHLEPA_RECON_TIMEOUT", "12.5")
    monkeypatch.setenv("SHLEPA_RECON_MAX_OUTPUT", "1234")
    cfg = load_config()
    assert cfg.tools.recon.timeout == 12.5
    assert cfg.tools.recon.max_output == 1234
    monkeypatch.setenv("SHLEPA_RECON_TIMEOUT", "not-a-number")
    assert load_config().tools.recon.timeout == 30.0  # invalid: ignored


# ---------------------------------------------------------------------------
# regression: pydantic-ai resolves the tool signature
# ---------------------------------------------------------------------------


def test_build_phase_agent_exposes_recon_tool():
    """The Literal mode arg must survive pydantic-ai signature resolution
    (mirrors the mitre_kb wiring regression test)."""
    from pydantic_ai.providers.openai import OpenAIProvider

    from shlepa_agent.model import TrackedModel
    from shlepa_agent.runner import build_phase_agent

    cfg = load_config()
    cfg.tools.recon.enabled = True
    for phase in cfg.phases.values():
        if "recon" not in phase.tools:
            phase.tools.append("recon")
    model = TrackedModel(
        "m", OpenAIProvider(base_url="http://localhost:1/v1", api_key="k"), cfg
    )
    agent = build_phase_agent(model, cfg, get_phase("work"), "TASK")
    assert "recon" in set(agent._function_toolset.tools)
