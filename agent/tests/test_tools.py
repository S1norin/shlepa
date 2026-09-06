"""Tests for the modular tool system (registry + per-tool behavior)."""

import asyncio
from types import SimpleNamespace

from shlepa_agent.config import load_config
from shlepa_agent.tools import ALL_TOOLS, get_tools
from shlepa_agent.tools.base import AgentDeps


def _cfg() -> object:
    return load_config()


def _ctx(tmp_path, cfg=None, clock=None):
    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=clock or (lambda: 0.0))
    return SimpleNamespace(deps=deps)


def test_registry_has_all_tools():
    assert set(ALL_TOOLS) == {
        "read", "write", "edit", "bash", "recon", "search",
        "code_search", "file_outline", "log_triage",
        # MITRE KB tool: off by default (+mitre-kb arm), see test_mitre_kb.py
        "mitre_kb",
    }



def test_registry_default_config_search_tools_in_tooled_phases(monkeypatch):
    # baseline behavior: with AGENT_CODE_SEARCH unset the packaged config
    # names the code-search tools in plan/work; the toolless review and the
    # legacy emergency phase never register them.
    from shlepa_agent.phases import get_phase

    monkeypatch.delenv("AGENT_CODE_SEARCH", raising=False)
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    cfg = _cfg()
    for phase_id in ("plan", "work"):
        names = [t.name for t in get_tools(cfg, get_phase(phase_id).tools(cfg))]
        assert "code_search" in names
        assert "file_outline" in names
    for phase_id in ("commit", "emergency"):
        names = [t.name for t in get_tools(cfg, get_phase(phase_id).tools(cfg))]
        assert "code_search" not in names
        assert "file_outline" not in names


def test_registry_returns_configured_subset():
    cfg = _cfg()
    tools = get_tools(cfg, ["bash", "write"])
    assert [t.name for t in tools] == ["bash", "write"]


def test_registry_skips_disabled_tools():
    cfg = _cfg()
    cfg.tools.edit.enabled = False
    tools = get_tools(cfg, ["bash", "edit"])
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


def test_bash_per_call_timeout(tmp_path):
    from shlepa_agent.tools.bash import bash

    out = asyncio.run(bash(_ctx(tmp_path), command="sleep 5", timeout=0.5))
    assert "[exit_code] 124 (KILLED after 1s timeout" in out


def test_bash_timeout_clamped_to_max_and_announced(tmp_path):
    from shlepa_agent.tools.bash import bash

    out = asyncio.run(bash(_ctx(tmp_path), command="echo ok", timeout=9999))
    assert "timeout clamped to 30s (max)" in out
    assert "[exit_code] 0" in out and "ok" in out


def test_bash_timeout_clamped_to_floor_and_announced(tmp_path):
    from shlepa_agent.tools.bash import bash

    out = asyncio.run(bash(_ctx(tmp_path), command="sleep 3", timeout=0.0001))
    assert "timeout clamped to 1s (min)" in out
    assert "[exit_code] 124" in out


def _untrusted_body(out: str) -> str:
    """Extract the body between the UNTRUSTED TEXT markers of a tool result."""
    start = out.index("UNTRUSTED TEXT ---------------\n")
    end = out.index("\nEND OF UNTRUSTED TEXT-----------")
    return out[start + len("UNTRUSTED TEXT ---------------\n"):end]


def test_bash_output_truncated_to_configured_limit(tmp_path):
    from shlepa_agent.tools.bash import bash

    cfg = _cfg()
    cfg.tools.bash.max_output = 50
    out = asyncio.run(bash(_ctx(tmp_path, cfg), command="echo " + "x" * 200))
    assert "[output truncated to 50 chars]" in out
    assert len(_untrusted_body(out)) < 200


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------


def _edit(tmp_path, edits, path="f.txt"):
    from shlepa_agent.tools.edit import edit

    return asyncio.run(edit(_ctx(tmp_path), path=path, edits=edits))


def test_edit_unique_in_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("one\ntwo\nthree\n")
    out = _edit(tmp_path, [{"oldText": "two", "newText": "TWO"}])
    assert "1 block" in out
    assert f.read_text() == "one\nTWO\nthree\n"


def test_edit_non_unique_in_file_is_error(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\na\n")
    out = _edit(tmp_path, [{"oldText": "a", "newText": "A"}])
    assert "found 2 times" in out
    assert "line" in out  # hint with line numbers
    assert f.read_text() == "a\nb\na\n"  # untouched


def test_edit_line_scoped_unique_in_line(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\na\n")
    out = _edit(tmp_path, [{"oldText": "a", "newText": "A", "line": 0}])
    assert "1 block" in out
    assert f.read_text() == "A\nb\na\n"


def test_edit_line_scoped_not_unique_in_line_is_error(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a a\n")
    out = _edit(tmp_path, [{"oldText": "a", "newText": "A", "line": 0}])
    assert "found 2 times on line 0" in out
    assert f.read_text() == "a a\n"


def test_edit_line_scoped_not_on_line_gives_hint(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x\ny\n")
    out = _edit(tmp_path, [{"oldText": "y", "newText": "z", "line": 0}])
    assert "not found on line 0" in out
    assert "line 1" in out  # hint where it actually is
    assert f.read_text() == "x\ny\n"


def test_edit_line_out_of_range(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x\n")
    out = _edit(tmp_path, [{"oldText": "x", "newText": "y", "line": 9}])
    assert "out of range" in out
    assert f.read_text() == "x\n"


def test_edit_multiline_oldtext_without_line(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\nc\n")
    out = _edit(tmp_path, [{"oldText": "a\nb", "newText": "AB"}])
    assert "1 block" in out
    assert f.read_text() == "AB\nc\n"


def test_edit_multiline_oldtext_with_line_is_error(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\n")
    out = _edit(tmp_path, [{"oldText": "a\nb", "newText": "AB", "line": 0}])
    assert "single line" in out or "line" in out.lower()
    assert f.read_text() == "a\nb\n"


def test_edit_multiple_blocks_in_one_call(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("host=127.0.0.1\nport=80\n")
    out = _edit(
        tmp_path,
        [
            {"oldText": "127.0.0.1", "newText": "0.0.0.0"},
            {"oldText": "80", "newText": "443"},
        ],
    )
    assert "2 block(s)" in out
    assert f.read_text() == "host=0.0.0.0\nport=443\n"


def test_edit_overlapping_blocks_are_error(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("abc\n")
    out = _edit(tmp_path, [{"oldText": "ab"}, {"oldText": "bc"}])
    assert "overlap" in out
    assert f.read_text() == "abc\n"


def test_edit_multiline_oldtext_ambiguous_has_no_line_hint(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("a\nb\na\nb\n")
    out = _edit(tmp_path, [{"oldText": "a\nb", "newText": "AB"}])
    assert "found 2 times" in out
    assert "lines []" not in out
    assert f.read_text() == "a\nb\na\nb\n"


def test_edit_missing_file(tmp_path):
    out = _edit(tmp_path, [{"oldText": "x", "newText": "y"}], path="nope.txt")
    assert "File not found" in out


def test_edit_empty_oldtext_or_edits_are_errors(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x\n")
    assert "oldText" in _edit(tmp_path, [{"oldText": "", "newText": "y"}])
    assert "edits" in _edit(tmp_path, [])
    assert f.read_text() == "x\n"


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


def _write(tmp_path, **kwargs):
    from shlepa_agent.tools.write import write

    cfg = kwargs.pop("cfg", None)
    return asyncio.run(write(_ctx(tmp_path, cfg), **kwargs))


def test_write_creates_file_with_exact_content(tmp_path):
    out = _write(tmp_path, path="sub/out.txt", text="abc")
    assert "Wrote 3 chars" in out
    assert (tmp_path / "sub" / "out.txt").read_bytes() == b"abc"  # no trailing newline


def test_write_existing_file_is_error_and_untouched(tmp_path):
    (tmp_path / "f.txt").write_text("old")
    out = _write(tmp_path, path="f.txt", text="new")
    assert "already exists" in out
    assert "edit" in out  # hint what to use instead
    assert (tmp_path / "f.txt").read_text() == "old"


def test_write_relative_path_resolves_to_workdir(tmp_path):
    _write(tmp_path, path="rel.txt", text="x")
    assert (tmp_path / "rel.txt").exists()


def test_write_empty_text(tmp_path):
    out = _write(tmp_path, path="empty.txt", text="")
    assert "Wrote 0 chars" in out
    assert (tmp_path / "empty.txt").read_bytes() == b""


# ---------------------------------------------------------------------------
# read
# ---------------------------------------------------------------------------


def _read(tmp_path, **kwargs):
    from shlepa_agent.tools.read import read

    cfg = kwargs.pop("cfg", None)
    return asyncio.run(read(_ctx(tmp_path, cfg), **kwargs))


def test_read_default_first_page_100_lines(tmp_path):
    (tmp_path / "f.txt").write_text("\n".join(f"line{i:03d}" for i in range(150)) + "\n")
    out = _read(tmp_path, path="f.txt")
    assert "line000" in out and "line099" in out
    assert "line100" not in out
    assert "50 more lines; continue with offset=100" in out


def test_read_offset_window_zero_based(tmp_path):
    (tmp_path / "f.txt").write_text("\n".join(f"line{i:03d}" for i in range(20)) + "\n")
    out = _read(tmp_path, path="f.txt", offset=5, limit=3)
    assert "line005" in out and "line007" in out
    assert "line004" not in out and "line008" not in out
    assert "12 more lines; continue with offset=8" in out


def test_read_limit_clamped_to_max_and_announced(tmp_path):
    (tmp_path / "f.txt").write_text("\n".join(f"line{i:03d}" for i in range(300)) + "\n")
    out = _read(tmp_path, path="f.txt", offset=0, limit=5000)
    assert "limit clamped to 100" in out
    assert "line099" in out and "line100" not in out
    assert "200 more lines; continue with offset=100" in out


def test_read_char_cap_mid_line_with_continuation(tmp_path):
    # one 10000-char line: the 4000-char cap cuts it mid-line
    (tmp_path / "big.txt").write_text("x" * 10000)
    out = _read(tmp_path, path="big.txt")
    assert "output truncated to 4000 chars" in out
    assert "continue with offset=0" in out
    assert len(_untrusted_body(out)) <= 4000


def test_read_char_cap_full_lines(tmp_path):
    # 100 lines x 103 chars (102 + \n) = ~10293 chars; 4000-char cap keeps
    # 38 full lines (3914 chars) and cuts the 39th mid-line
    (tmp_path / "f.txt").write_text("\n".join("z" * 100 + f"-{i}" for i in range(100)) + "\n")
    out = _read(tmp_path, path="f.txt")
    assert "output truncated to 4000 chars" in out
    assert "continue with offset=38" in out


def test_read_offset_past_eof(tmp_path):
    (tmp_path / "f.txt").write_text("a\nb\nc\n")
    out = _read(tmp_path, path="f.txt", offset=10)
    assert "End of file" in out
    assert "3 line(s)" in out


def test_read_missing_file(tmp_path):
    out = _read(tmp_path, path="missing.txt")
    assert "File not found" in out


def test_read_binary_error(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    out = _read(tmp_path, path="bin.dat")
    assert "Binary file" in out


def test_read_directory_error(tmp_path):
    out = _read(tmp_path, path=".")
    assert "directory" in out.lower()


# ---------------------------------------------------------------------------
# instrumented result format (timing header, NOTE/FAILED lines, UNTRUSTED)
# ---------------------------------------------------------------------------


def _ctx_clocked(tmp_path, clock=None, cfg=None):
    return _ctx(tmp_path, cfg=cfg, clock=clock or (lambda: 100.0))


def test_result_header_has_timing(tmp_path):
    from shlepa_agent.tools.bash import bash

    ctx = _ctx_clocked(tmp_path)
    out = asyncio.run(bash(ctx, command="echo hi"))
    assert out.startswith("[tool] bash(")
    assert "spent=" in out
    assert "ended_at=100.0s" in out
    # no time_left: v5 has no global hard deadline
    assert "time_left" not in out


def test_untrusted_framing_on_read_and_bash_only(tmp_path):
    from shlepa_agent.tools.bash import bash
    from shlepa_agent.tools.read import read
    from shlepa_agent.tools.write import write

    ctx = _ctx_clocked(tmp_path)
    (tmp_path / "f.txt").write_text("data\n")
    r = asyncio.run(read(ctx, path="f.txt"))
    assert "UNTRUSTED TEXT ---------------" in r
    assert "END OF UNTRUSTED TEXT-----------" in r
    b = asyncio.run(bash(ctx, command="echo hi"))
    assert "UNTRUSTED TEXT ---------------" in b
    w = asyncio.run(write(ctx, path="n.txt", text="x"))
    assert "UNTRUSTED TEXT" not in w


def test_failed_line_on_error(tmp_path):
    from shlepa_agent.tools.read import read

    ctx = _ctx_clocked(tmp_path)
    out = asyncio.run(read(ctx, path="nope.txt"))
    assert "FAILED: File not found: nope.txt" in out


def test_note_line_for_clamped_params(tmp_path):
    from shlepa_agent.tools.read import read

    ctx = _ctx_clocked(tmp_path)
    (tmp_path / "big.txt").write_text("x\n" * 300)
    out = asyncio.run(read(ctx, path="big.txt", limit=999))
    assert "NOTE: limit clamped to 100" in out


def test_args_in_header_are_truncated(tmp_path):
    from shlepa_agent.tools.write import write

    ctx = _ctx_clocked(tmp_path)
    out = asyncio.run(write(ctx, path="big.txt", text="z" * 500))
    assert "…(truncated)" in out.splitlines()[0]


# ---------------------------------------------------------------------------
# file size caps + per-call timeout (#61)
# ---------------------------------------------------------------------------


def _sparse(path, mb: float) -> None:
    """Create a sparse file of the given size (no real disk usage)."""
    with open(path, "wb") as fh:
        fh.seek(int(mb * 1024 * 1024))
        fh.write(b"\x00")


def test_read_file_over_size_limit_is_rejected(tmp_path):
    from shlepa_agent.tools.read import read

    _sparse(tmp_path / "big.bin", 200)
    out = asyncio.run(read(_ctx(tmp_path), path="big.bin"))
    assert "FAILED" in out
    assert "file is 200.0 MB, limit is 100 MB" in out
    assert "use bash: head/tail/grep/sed -n 'A,Bp'" in out
    assert "<empty>" in out  # content was never loaded (empty body on failure)


def test_read_size_limit_comes_from_config(tmp_path):
    from shlepa_agent.tools.read import read

    (tmp_path / "f.bin").write_text("a" * (2 * 1024 * 1024))  # real 2 MB text
    cfg = _cfg()
    cfg.tools.read.max_file_mb = 1.0
    out = asyncio.run(read(_ctx(tmp_path, cfg), path="f.bin"))
    assert "file is 2.0 MB, limit is 1 MB" in out
    cfg2 = _cfg()
    cfg2.tools.read.max_file_mb = 3.0
    out2 = asyncio.run(read(_ctx(tmp_path, cfg2), path="f.bin"))
    assert "FAILED" not in out2


def test_edit_file_over_size_limit_is_rejected(tmp_path):
    from shlepa_agent.tools.edit import edit

    _sparse(tmp_path / "big.txt", 150)
    out = asyncio.run(
        edit(_ctx(tmp_path), path="big.txt", edits=[{"oldText": "x", "newText": "y"}])
    )
    assert "FAILED" in out
    assert "file is 150.0 MB, limit is 100 MB" in out
    assert "use bash: head/tail/grep/sed -n 'A,Bp'" in out


def test_edit_size_limit_comes_from_config(tmp_path):
    from shlepa_agent.tools.edit import edit

    _sparse(tmp_path / "f.txt", 2)
    cfg = _cfg()
    cfg.tools.edit.max_file_mb = 1.0
    out = asyncio.run(
        edit(_ctx(tmp_path, cfg), path="f.txt", edits=[{"oldText": "x", "newText": "y"}])
    )
    assert "file is 2.0 MB, limit is 1 MB" in out


def test_read_timeout_reports_message(tmp_path, monkeypatch):
    import time

    import shlepa_agent.tools.base as base_mod
    import shlepa_agent.tools.read as read_mod
    from shlepa_agent.tools.read import read

    monkeypatch.setattr(base_mod, "FILE_TOOL_TIMEOUT_S", 0.02)
    f = tmp_path / "slow.txt"
    f.write_text("hello\n")
    orig_load = read_mod._load_text

    def slow_load(p, _path):
        time.sleep(0.3)
        return orig_load(p, _path)

    monkeypatch.setattr(read_mod, "_load_text", slow_load)
    out = asyncio.run(read(_ctx(tmp_path), path="slow.txt"))
    assert "tool timed out after 0.02s" in out


def test_write_timeout_reports_message(tmp_path, monkeypatch):
    import time
    from pathlib import Path

    import shlepa_agent.tools.base as base_mod
    from shlepa_agent.tools.write import write

    monkeypatch.setattr(base_mod, "FILE_TOOL_TIMEOUT_S", 0.02)
    orig_write_text = Path.write_text

    def slow_write_text(self, data, encoding=None):
        time.sleep(0.3)
        return orig_write_text(self, data, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", slow_write_text)
    out = asyncio.run(write(_ctx(tmp_path), path="slow.txt", text="hi"))
    assert "tool timed out after 0.02s" in out


def test_edit_timeout_reports_message(tmp_path, monkeypatch):
    import time
    from pathlib import Path

    import shlepa_agent.tools.base as base_mod
    from shlepa_agent.tools.edit import edit

    monkeypatch.setattr(base_mod, "FILE_TOOL_TIMEOUT_S", 0.02)
    f = tmp_path / "slow.txt"
    f.write_text("hello\n")
    orig_read_text = Path.read_text

    def slow_read_text(self, encoding=None):
        time.sleep(0.3)
        return orig_read_text(self, encoding=encoding)

    monkeypatch.setattr(Path, "read_text", slow_read_text)
    out = asyncio.run(
        edit(_ctx(tmp_path), path="slow.txt", edits=[{"oldText": "hello", "newText": "bye"}])
    )
    assert "tool timed out after 0.02s" in out


# ---------------------------------------------------------------------------
# bash: bounded output, process-group kill, 30s cap (#60)
# ---------------------------------------------------------------------------


def test_bash_unbounded_output_is_bounded_with_drop_marker(tmp_path):
    import subprocess
    import time

    from shlepa_agent.tools.bash import bash

    cfg = _cfg()
    cfg.tools.bash.timeout = 2.0
    # unbounded producer: /dev/zero never reaches EOF, so the 2s timeout
    # is guaranteed to fire regardless of machine speed
    out = asyncio.run(bash(_ctx(tmp_path, cfg), command="cat /dev/zero"))
    assert "[exit_code] 124" in out  # killed at the 2s timeout
    assert "bytes dropped" in out  # head+tail retention marker
    # retention is bounded by the per-stream cap even though the process
    # produced ~1 GB
    assert len(_untrusted_body(out)) <= 20000
    # and nothing of the command's process tree survives the kill
    time.sleep(0.2)
    p = subprocess.run(["pgrep", "-f", "dd if=/dev/zero"], capture_output=True)
    assert p.returncode != 0  # no matches


def test_bash_timeout_kills_whole_process_group(tmp_path):
    import subprocess
    import time

    from shlepa_agent.tools.bash import bash

    cfg = _cfg()
    cfg.tools.bash.timeout = 2.0
    out = asyncio.run(
        bash(_ctx(tmp_path, cfg), command="sh -c 'sleep 317 & exec sleep 1'")
    )
    assert "[exit_code] 124" in out
    # the backgrounded child (a separate process from the killed shell) must
    # be gone too: the kill goes to the whole session/group
    time.sleep(0.2)
    p = subprocess.run(["pgrep", "-f", "sleep 317"], capture_output=True)
    assert p.returncode != 0  # no matches
