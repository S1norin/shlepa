"""Tests for the compact code-search primitives (rg engine + file_outline).

Covers the cs-rg-engine acceptance criteria:
1. per-file grouped windows with file:line-range headers + deduped matches
2. strict token budget (chars/4) with a truncation marker
3. missing rg -> compact error string, never raises
4. file_outline fallback lists def/class/func symbols with line ranges
"""

import shutil

import pytest

from shlepa_agent.code_search import code_search, file_outline

RG = shutil.which("rg")

AUTH_PY = '''\
from app.db import get_pool

SECRET_NOTE = "flag{hidden}"




def login(request):
    user = request.form["user"]
    password = request.form["pass"]




    pool = get_pool()
    cur = pool.execute("SELECT id FROM users WHERE name = '%s'" % user)
    row = cur.fetchone()
    return row



def logout(request):
    return "bye"
'''

DB_PY = '''\
import sqlite3


DB_PATH = "app.db"




def get_pool():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id FROM users")
    return cur
'''

NOTES_TXT = "dup SELECT id FROM users and again SELECT id FROM users here\n"


def make_corpus(tmp_path):
    (tmp_path / "app" / "routers").mkdir(parents=True)
    (tmp_path / "app" / "routers" / "auth.py").write_text(AUTH_PY)
    (tmp_path / "app" / "db.py").write_text(DB_PY)
    (tmp_path / "app" / "notes.txt").write_text(NOTES_TXT)
    return tmp_path


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_rg_windows_and_dedup(tmp_path):
    make_corpus(tmp_path)
    result = code_search("SELECT id FROM users", ".", workdir=tmp_path)

    # Per-file grouped windows with file:line-range headers...
    assert "app/db.py:9-13" in result
    assert "app/routers/auth.py:13-19" in result
    # ...with enclosing-symbol annotation...
    assert "(def get_pool():)" in result
    assert "(def login(request):)" in result
    # ...and window content lines.
    assert "conn = sqlite3.connect(DB_PATH)" in result
    assert "pool = get_pool()" in result

    # Dedup: two matches on the same line yield a single window, and no
    # file contributes more than one window header.
    assert "app/notes.txt:1-1" in result
    assert result.count("app/notes.txt") == 1
    assert result.count("app/db.py:") == 1  # single window, no duplicates
    assert result.count("app/routers/auth.py:") == 1


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_token_budget(tmp_path):
    make_corpus(tmp_path)
    big = tmp_path / "big.txt"
    big.write_text("\n".join(f"line {i} zzneedle end" for i in range(50)) + "\n")

    # The full result is ~1.4k chars; a 30-token budget is 120 chars.
    result = code_search("zzneedle", ".", workdir=tmp_path, max_tokens=30)
    assert len(result) <= 30 * 4
    assert "truncated" in result


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_no_match(tmp_path):
    make_corpus(tmp_path)
    result = code_search("definitely-not-there-xyz", ".", workdir=tmp_path)
    assert "no matches" in result


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_bad_path(tmp_path):
    result = code_search("SELECT", "no/such/dir", workdir=tmp_path)
    assert "path not found" in result


def test_code_search_missing_rg_graceful(tmp_path, monkeypatch):
    make_corpus(tmp_path)
    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    # rg_bin=None forces shutil.which() lookup against the stripped PATH.
    result = code_search("SELECT id FROM users", ".", workdir=tmp_path)
    assert "code_search" in result
    assert "ripgrep" in result or "rg" in result
    assert "grep" in result  # suggests the bash fallback


def test_file_outline_symbols_and_ranges(tmp_path):
    make_corpus(tmp_path)
    result = file_outline("app/routers/auth.py", workdir=tmp_path)
    # Both functions listed with their starting lines...
    assert "def login(request):" in result
    assert "def logout(request):" in result
    # ...with line ranges: login runs 8..21 (logout starts at 22),
    # logout runs 22..23 (EOF).
    assert "8-21" in result
    assert "22-23" in result
    # Non-declaration lines (plain assignments) are not symbols.
    assert "SECRET_NOTE" not in result


def test_file_outline_missing_file(tmp_path):
    result = file_outline("no/such/file.py", workdir=tmp_path)
    assert "file not found" in result


def test_file_outline_no_symbols(tmp_path):
    (tmp_path / "plain.txt").write_text("hello\nworld\n")
    result = file_outline("plain.txt", workdir=tmp_path)
    assert "no def/class/func symbols" in result
