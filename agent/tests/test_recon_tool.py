"""Tests for the recon tool (wrapper around tools/recon.py).

The real script is exercised only in read-only --data mode on a small
fixture tree (fast, deterministic, no network); mode wiring, the wall
cap, and truncation use a fake script so the tests stay fast and hermetic.
"""

import asyncio
import json
import time

from shlepa_agent.config import load_config
from shlepa_agent.tools import ALL_TOOLS
from shlepa_agent.tools import recon_tool
from shlepa_agent.tools.base import AgentDeps

import pytest


def _ctx(tmp_path, cfg=None, clock=None):
    from types import SimpleNamespace

    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=clock or (lambda: 0.0))
    return SimpleNamespace(deps=deps)


def _write_fake_script(tmp_path, body: str, name="fake_recon.py") -> "object":
    p = tmp_path / name
    p.write_text(
        "import sys, json\n"
        "print(json.dumps({'argv': sys.argv[1:]}))\n"
        if body == "argv"
        else f"import sys\nsys.stdout.write({body!r})\n"
    )
    return p


def test_recon_registered():
    assert "recon" in ALL_TOOLS
    assert ALL_TOOLS["recon"].name == "recon"


def test_recon_mode_wiring_url(tmp_path, monkeypatch):
    script = _write_fake_script(tmp_path, "argv")
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: script)
    ctx = _ctx(tmp_path)
    out = asyncio.run(recon_tool.recon(ctx, mode="url", target="http://127.0.0.1/x"))
    assert '"argv": ["http://127.0.0.1/x"]' in out


def test_recon_mode_wiring_code_and_data(tmp_path, monkeypatch):
    script = _write_fake_script(tmp_path, "argv")
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: script)
    ctx = _ctx(tmp_path)
    out_code = asyncio.run(recon_tool.recon(ctx, mode="code", target="src"))
    assert '"argv": ["--code", "src"]' in out_code
    out_data = asyncio.run(recon_tool.recon(ctx, mode="data", target="evidence"))
    assert '"argv": ["--data", "evidence"]' in out_data


def test_recon_unknown_mode_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: tmp_path / "x.py")
    out = asyncio.run(recon_tool.recon(_ctx(tmp_path), mode="warp", target="x"))
    assert "FAILED" in out
    assert "unknown recon mode" in out


def test_recon_missing_script_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: None)
    out = asyncio.run(recon_tool.recon(_ctx(tmp_path), mode="code", target="src"))
    assert "FAILED" in out
    assert "not found" in out


def test_recon_hard_cap_kills_slow_script(tmp_path, monkeypatch):
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: script)
    monkeypatch.setattr(recon_tool, "RECON_TIMEOUT_S", 1.0)
    t0 = time.monotonic()
    out = asyncio.run(recon_tool.recon(_ctx(tmp_path), mode="code", target="src"))
    elapsed = time.monotonic() - t0
    assert "FAILED" in out
    assert "timed out after 1s" in out
    assert elapsed < 10  # the cap, not the script, ended the call


def test_recon_output_capped_with_marker(tmp_path, monkeypatch):
    big = "x" * 20000
    script = _write_fake_script(tmp_path, big)
    monkeypatch.setattr(recon_tool, "find_recon_script", lambda: script)
    ctx = _ctx(tmp_path)
    out = asyncio.run(recon_tool.recon(ctx, mode="data", target="d"))
    # body itself is at most the 8 KB cap (plus the tool-result scaffolding)
    assert "UNTRUSTED TEXT" in out
    start = out.index("UNTRUSTED TEXT ---------------\n")
    end = out.index("\nEND OF UNTRUSTED TEXT-----------")
    body = out[start + len("UNTRUSTED TEXT ---------------\n"):end]
    assert len(body) <= recon_tool.DEFAULT_MAX_OUTPUT
    assert len(body) == recon_tool.DEFAULT_MAX_OUTPUT  # capped exactly


def test_recon_data_mode_read_only_on_fixture_tree(tmp_path):
    """The real script in --data mode maps a small tree and must not
    create, modify, or delete anything in it."""
    fixture = tmp_path / "evidence"
    (fixture / "sub").mkdir(parents=True)
    (fixture / "a.txt").write_text("flag{abc}\n")
    (fixture / "sub" / "b.txt").write_text("noise\n")
    before = {
        p.relative_to(fixture).as_posix(): p.read_bytes()
        for p in fixture.rglob("*") if p.is_file()
    }
    script = recon_tool.find_recon_script()
    if script is None:
        pytest.skip("tools/recon.py not resolvable in this environment")
    ctx = _ctx(tmp_path)
    out = asyncio.run(
        recon_tool.recon(ctx, mode="data", target=str(fixture))
    )
    assert "FAILED" not in out
    assert "UNTRUSTED TEXT" in out
    after = {
        p.relative_to(fixture).as_posix(): p.read_bytes()
        for p in fixture.rglob("*") if p.is_file()
    }
    assert before == after  # read-only by construction
