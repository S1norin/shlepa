"""Tests for the search tool (stdlib-only grep/glob/ls, capped output)."""

import asyncio
from types import SimpleNamespace

import pytest

from shlepa_agent.config import load_config
from shlepa_agent.tools import ALL_TOOLS
from shlepa_agent.tools import search_tool
from shlepa_agent.tools.base import AgentDeps


def _ctx(tmp_path, cfg=None):
    cfg = cfg if cfg is not None else load_config()
    deps = AgentDeps(workdir=tmp_path, cfg=cfg, clock=lambda: 0.0)
    return SimpleNamespace(deps=deps)


@pytest.fixture
def tree(tmp_path):
    """A small fixture tree: nested text, a skip dir, and a binary file."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "deep").mkdir()
    (tmp_path / "src" / "app.py").write_text("needle here\nnothing\nneedle again\n")
    (tmp_path / "src" / "deep" / "note.txt").write_text("needle in depth\n")
    (tmp_path / "data.json").write_text('{"key": "value"}\n')
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "head.txt").write_text("needle in git (must not match)\n")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01needle\x00")
    return tmp_path


def _search(tmp_path, **kwargs):
    kwargs.setdefault("mode", "grep")
    return asyncio.run(search_tool.search(_ctx(tmp_path), **kwargs))


def _body(out: str) -> str:
    assert "UNTRUSTED TEXT" in out, out
    start = out.index("UNTRUSTED TEXT ---------------\n")
    end = out.index("\nEND OF UNTRUSTED TEXT-----------")
    return out[start + len("UNTRUSTED TEXT ---------------\n"):end]


def test_search_registered():
    assert "search" in ALL_TOOLS
    assert ALL_TOOLS["search"].name == "search"


def test_grep_substring_counts_and_shows(tree):
    out = _search(tree, pattern="needle")
    body = _body(out)
    assert "3 total match(es)" in body
    assert "src/app.py:1: needle here" in body
    assert "src/deep/note.txt:1: needle in depth" in body
    # .git and the binary file are excluded
    assert ".git" not in body
    assert "blob.bin" not in body


def test_grep_regex_mode(tree):
    out = _search(tree, pattern="ne[a-z]+le", is_regex=True)
    body = _body(out)
    assert "3 total match(es)" in body
    assert "(regex)" in body


def test_grep_invalid_regex_is_failure(tree):
    out = _search(tree, pattern="ne[a-z+le", is_regex=True)
    assert "FAILED" in out
    assert "invalid regex" in out


def test_grep_limit_shows_first_n_but_counts_all(tree):
    big = tree / "big.txt"
    big.write_text("needle\n" * 120)
    out = _search(tree, pattern="needle", limit=5)
    body = _body(out)
    assert "123 total match(es)" in body
    assert "showing first 5" in body
    shown = [l for l in body.splitlines() if l.startswith("big.txt:")]
    assert len(shown) == 5
    assert "118 more match(es) not shown" in out


def test_grep_no_matches(tree):
    out = _search(tree, pattern="no_such_string_zzz")
    body = _body(out)
    assert "0 total match(es)" in body
    assert "<no matches>" in body


def test_glob_matches_relative_paths(tree):
    out = _search(tree, mode="glob", pattern="*.py")
    body = _body(out)
    assert "1 file(s) total" in body
    assert "src/app.py" in body


def test_glob_double_star(tree):
    out = _search(tree, mode="glob", pattern="**/*.txt")
    body = _body(out)
    assert "1 file(s) total" in body  # .git/head.txt is skipped
    assert "src/deep/note.txt" in body


def test_ls_lists_directory(tree):
    out = _search(tree, mode="ls", pattern="x", path="src")
    body = _body(out)
    assert "2 entries" in body
    assert "app.py" in body
    assert "deep/" in body  # dirs marked


def test_unknown_mode_is_failure(tree):
    out = _search(tree, mode="warp", pattern="x")
    assert "FAILED" in out
    assert "unknown search mode" in out


def test_empty_pattern_is_failure(tree):
    out = _search(tree, pattern="")
    assert "FAILED" in out
    assert "pattern is empty" in out


def test_missing_path_is_failure(tree):
    out = _search(tree, pattern="x", path="no_such_dir")
    assert "FAILED" in out
    assert "path not found" in out


def test_large_corpus_capped_and_tree_unchanged(tmp_path):
    """A large corpus stays within the 8 KB result cap and the walk has a
    deadline; nothing is ever written."""
    for i in range(400):
        d = tmp_path / f"d{i % 40}"
        d.mkdir(exist_ok=True)
        (d / f"f{i}.txt").write_text(f"line {i}\nmarker {i}\n" * 50)
    before = sorted(
        str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")
    )
    out = _search(tmp_path, pattern="marker", limit=200)
    after = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert before == after  # no write side effects
    body = _body(out)
    assert len(body) <= search_tool.DEFAULT_MAX_OUTPUT
    assert "20000 total match(es)" in body
    assert "19800 more match(es) not shown" in out


def test_walk_deadline_returns_partial_results(tmp_path, monkeypatch):
    for i in range(50):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "f.txt").write_text("needle\n" * 500)
    monkeypatch.setattr(search_tool, "WALK_DEADLINE_S", 0.0)
    out = _search(tmp_path, pattern="needle", limit=5)
    assert "partial results" in out


def test_line_excerpt_cuts_long_lines(tree):
    long_line = "start " + "z" * 1000 + " end"
    (tree / "long.txt").write_text(long_line + "\n")
    out = _search(tree, pattern="start")
    body = _body(out)
    line = next(l for l in body.splitlines() if l.startswith("long.txt:"))
    assert len(line) < 300  # the 200-char excerpt keeps it bounded
