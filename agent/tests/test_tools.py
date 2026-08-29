"""Tests for the modular tool system (registry + per-tool behavior)."""

import asyncio
from types import SimpleNamespace

from shlepa_agent.config import load_config
from shlepa_agent.tools import ALL_TOOLS, get_tools
from shlepa_agent.tools.base import AgentDeps


def _cfg() -> object:
    return load_config()


def _ctx(tmp_path, cfg=None):
    cfg = cfg if cfg is not None else load_config()
    return SimpleNamespace(deps=AgentDeps(workdir=tmp_path, cfg=cfg))


def test_registry_has_all_v1_tools():
    assert set(ALL_TOOLS) == {"bash", "read_file", "write_file", "append_file", "apply_diff"}


def test_registry_returns_configured_subset():
    cfg = _cfg()
    tools = get_tools(cfg, ["bash", "write_file"])
    assert [t.name for t in tools] == ["bash", "write_file"]


def test_registry_skips_disabled_tools():
    cfg = _cfg()
    cfg.tools.apply_diff.enabled = False
    tools = get_tools(cfg, ["bash", "apply_diff"])
    assert [t.name for t in tools] == ["bash"]


def test_registry_unknown_tool_raises():
    import pytest

    with pytest.raises(KeyError):
        get_tools(_cfg(), ["nope"])


def test_tools_have_non_empty_english_notes():
    for tool in ALL_TOOLS.values():
        assert tool.note
        assert tool.name in tool.note


# ---------------------------------------------------------------------------
# bash
# ---------------------------------------------------------------------------


def test_bash_runs_and_formats(tmp_path):
    from shlepa_agent.tools.bash import bash

    ctx = _ctx(tmp_path)
    out = asyncio.run(bash(ctx, command="echo hi"))
    assert "$ echo hi" in out
    assert "[exit_code] 0" in out
    assert "[stdout]\nhi" in out
    assert "[stderr]\n<empty>" in out


def test_bash_timeout_kill(tmp_path):
    from shlepa_agent.tools.bash import bash

    cfg = _cfg()
    cfg.tools.bash.timeout = 0.5
    out = asyncio.run(bash(_ctx(tmp_path, cfg), command="sleep 5"))
    assert "[exit_code] 124 (KILLED" in out
    assert "timeout - command was too slow or hung)" in out


def test_bash_output_truncated_to_configured_limit(tmp_path):
    from shlepa_agent.tools.bash import bash

    cfg = _cfg()
    cfg.tools.bash.max_output = 50
    out = asyncio.run(bash(_ctx(tmp_path, cfg), command="echo " + "x" * 200))
    assert "[output truncated to 50 chars]" in out
    assert len(out) < 200


# ---------------------------------------------------------------------------
# read_file / write_file / append_file
# ---------------------------------------------------------------------------


def test_write_file_exact_no_trailing_newline(tmp_path):
    from shlepa_agent.tools.write_file import write_file

    ctx = _ctx(tmp_path)
    result = asyncio.run(write_file(ctx, path="sub/out.txt", content="abc"))
    assert "Wrote exactly 3 chars" in result
    data = (tmp_path / "sub" / "out.txt").read_bytes()
    assert data == b"abc"  # no trailing newline


def test_append_file(tmp_path):
    from shlepa_agent.tools.append_file import append_file
    from shlepa_agent.tools.write_file import write_file

    ctx = _ctx(tmp_path)
    asyncio.run(write_file(ctx, path="f.txt", content="one"))
    result = asyncio.run(append_file(ctx, path="f.txt", content="two"))
    assert "Appended 3 chars" in result
    assert (tmp_path / "f.txt").read_text() == "onetwo"


def test_read_file_truncates_to_configured_limit(tmp_path):
    from shlepa_agent.tools.read_file import read_file

    (tmp_path / "big.txt").write_text("y" * 500)
    cfg = _cfg()
    cfg.tools.read_file.max_output = 100
    out = asyncio.run(read_file(_ctx(tmp_path, cfg), path="big.txt"))
    assert "[output truncated to 100 chars]" in out


def test_read_file_not_found(tmp_path):
    from shlepa_agent.tools.read_file import read_file

    out = asyncio.run(read_file(_ctx(tmp_path), path="missing.txt"))
    assert "File not found" in out


# ---------------------------------------------------------------------------
# apply_diff
# ---------------------------------------------------------------------------


def test_apply_diff_applies_patch(tmp_path):
    from shlepa_agent.tools.apply_diff import apply_diff

    f = tmp_path / "src.txt"
    f.write_text("hello world\n")
    diff = (
        f"--- {f}\n+++ {f}\n@@ -1 +1 @@\n-hello world\n+hello shlepa\n"
    )
    out = asyncio.run(apply_diff(_ctx(tmp_path), path=str(f), diff_content=diff))
    assert "Applied diff" in out
    assert f.read_text() == "hello shlepa\n"


def test_apply_diff_missing_file(tmp_path):
    from shlepa_agent.tools.apply_diff import apply_diff

    out = asyncio.run(apply_diff(_ctx(tmp_path), path=str(tmp_path / "nope"), diff_content="x"))
    assert "File not found" in out
