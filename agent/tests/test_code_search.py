"""Tests for the compact code-search primitives (rg + SIFS engines).

Covers the cs-rg-engine acceptance criteria:
1. per-file grouped windows with file:line-range headers + deduped matches
2. strict token budget (chars/4) with a truncation marker
3. missing rg -> compact error string, never raises
4. file_outline fallback lists def/class/func symbols with line ranges

and the cs-sifs-adapter acceptance criteria (stub sifs executable):
5. same compact output shape, JSON envelope stripped
6. engine resolution: explicit > sifs-present > rg-fallback (never crash)
7. version mismatch vs the pinned provenance -> warning line
"""

import json
import shutil
from pathlib import Path

import pytest

from shlepa_agent.code_search import SIFS_PINNED_VERSION, code_search, file_outline

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
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path, engine="rg"
    )

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
    result = code_search(
        "zzneedle", ".", workdir=tmp_path, max_tokens=30, engine="rg"
    )
    assert len(result) <= 30 * 4
    assert "truncated" in result


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_no_match(tmp_path):
    make_corpus(tmp_path)
    result = code_search(
        "definitely-not-there-xyz", ".", workdir=tmp_path, engine="rg"
    )
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
    # Explicit rg engine + rg_bin=None forces shutil.which() lookup against
    # the stripped PATH (no engine fallback wanted here).
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path, engine="rg"
    )
    assert "code_search" in result
    assert "ripgrep" in result or "rg" in result
    assert "grep" in result  # suggests the bash fallback


def test_file_outline_symbols_and_ranges(tmp_path):
    make_corpus(tmp_path)
    result = file_outline(
        "app/routers/auth.py", workdir=tmp_path, engine="regex"
    )
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
    result = file_outline("plain.txt", workdir=tmp_path, engine="regex")
    assert "no def/class/func symbols" in result


# ---------------------------------------------------------------------------
# SIFS BM25 engine adapter (cs-sifs-adapter)
# ---------------------------------------------------------------------------

def _sifs_symbol(kind: str, line: int, name: str, end_line: int | None = None):
    sym = {
        "confidence": "high",
        "kind": kind,
        "line": line,
        "name": name,
        "origin": "line_pattern",
        "role": "definition",
    }
    if end_line is not None:
        sym["end_line"] = end_line
    return sym


#: Known sifs `search --json` payload: two files, definition-role symbols,
#: plus envelope fields (breadcrumbs/score/index_stats) that the adapter
#: must strip from the tool output.
SIFS_SEARCH_JSON = json.dumps(
    {
        "elapsed_ms": 3,
        "hint": None,
        "index_stats": {
            "indexed_files": 2,
            "languages": {"python": 2},
            "total_chunks": 2,
        },
        "limit": 5,
        "mode": "bm25",
        "query": "SELECT id FROM users",
        "results": [
            {
                "breadcrumbs": ["def get_pool"],
                "content": (
                    "def get_pool():\n    conn = sqlite3.connect(DB_PATH)\n"
                    "    return conn\n"
                ),
                "end_line": 13,
                "file_path": "app/db.py",
                "language": "python",
                "score": 0.9,
                "source": "bm25",
                "start_line": 9,
                "symbols": [_sifs_symbol("def", 9, "get_pool")],
            },
            {
                "breadcrumbs": ["def login"],
                "content": (
                    "def login(request):\n    pool = get_pool()\n"
                    "    return pool.execute(q)\n"
                ),
                "end_line": 12,
                "file_path": "app/routers/auth.py",
                "language": "python",
                "score": 0.8,
                "source": "bm25",
                "start_line": 8,
                "symbols": [_sifs_symbol("def", 8, "login")],
            },
        ],
        "source": "/somewhere",
        "truncated": False,
        "warnings": [],
    }
)

#: Known sifs `outline --json` payload (matches the AUTH_PY corpus: 23
#: lines, login 8-21, logout 22-23).
SIFS_OUTLINE_JSON = json.dumps(
    {
        "elapsed_ms": 2,
        "found": True,
        "kinds": [],
        "outline": {
            "chunk_count": 1,
            "chunks": [],
            "end_line": 23,
            "file_path": "routers/auth.py",
            "language": "python",
            "start_line": 1,
            "symbol_count": 2,
            "symbols": [
                _sifs_symbol("def", 8, "login", end_line=21),
                _sifs_symbol("def", 22, "logout", end_line=23),
            ],
        },
    }
)


STUB_TEMPLATE = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "sifs {version}"
  exit 0
fi
if [ "$1" = "search" ]; then
{search_body}
fi
if [ "$1" = "outline" ]; then
  cat <<'JSON2'
{outline_json}
JSON2
  exit 0
fi
echo "stub sifs: unknown subcommand" >&2
exit 2
"""


def make_stub(
    tmp_path: Path,
    *,
    version: str = SIFS_PINNED_VERSION,
    record_argv: bool = False,
    fail_search: bool = False,
    no_results: bool = False,
) -> Path:
    """Write an executable stub sifs that emits the known JSON payloads."""
    argv_rec = 'printf "%s\\n" "$@" > "$SIFS_STUB_ARGV_FILE"\n' if record_argv else ""
    if fail_search:
        search_body = '  echo "stub sifs: search failed" >&2\n  exit 1\n'
    elif no_results:
        search_body = (
            '  echo \'{"results": [], "index_stats": {"indexed_files": 0}}\'\n'
            "  exit 0\n"
        )
    else:
        search_body = (
            f"  {argv_rec}  cat <<'JSON'\n{SIFS_SEARCH_JSON}\nJSON\n  exit 0\n"
        )
    script = STUB_TEMPLATE.format(
        version=version, search_body=search_body, outline_json=SIFS_OUTLINE_JSON
    )
    stub = tmp_path / "sifs-stub"
    stub.write_text(script)
    stub.chmod(0o755)
    return stub


def test_code_search_sifs_compact_shape_and_envelope_strip(tmp_path):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path)
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path,
        engine="sifs", sifs_bin=str(stub),
    )
    # Same compact shape as the rg engine: ranked numbered entries with
    # file:line-range headers + symbol annotation + numbered body lines.
    assert "1. app/db.py:9-13  (def get_pool)" in result
    assert "2. app/routers/auth.py:8-12  (def login)" in result
    assert "     9: def get_pool():" in result
    assert "chunk(s) in 2 file(s)" in result
    assert result.startswith("sifs[bm25]:")
    # The JSON envelope is stripped: no envelope fields in the output.
    for key in ("breadcrumbs", "score", "index_stats", "confidence",
                "line_pattern", "elapsed_ms"):
        assert f'"{key}"' not in result


def test_code_search_sifs_version_mismatch_warns(tmp_path):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path, version="9.9.9")
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path,
        engine="sifs", sifs_bin=str(stub),
    )
    assert result.startswith("WARNING: sifs version 9.9.9")
    assert SIFS_PINNED_VERSION in result


def test_code_search_sifs_no_match(tmp_path):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path, no_results=True)
    result = code_search(
        "definitely-not-there-xyz", ".", workdir=tmp_path,
        engine="sifs", sifs_bin=str(stub),
    )
    assert "no matches" in result


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_sifs_missing_binary_falls_back_to_rg(tmp_path):
    make_corpus(tmp_path)
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path,
        engine="sifs", sifs_bin=str(tmp_path / "no-such-sifs"),
    )
    assert "fell back to rg" in result
    assert "app/db.py:" in result  # the rg engine produced real windows


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_sifs_engine_failure_degrades_with_note(tmp_path):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path, fail_search=True)
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path,
        engine="sifs", sifs_bin=str(stub),
    )
    assert "fell back to rg" in result
    assert "stub sifs: search failed" in result
    assert "app/db.py:" in result


@pytest.mark.skipif(RG is None, reason="ripgrep not available")
def test_code_search_auto_no_sifs_uses_rg_silently(tmp_path, monkeypatch):
    from shlepa_agent import code_search as cs

    make_corpus(tmp_path)
    monkeypatch.setattr(cs, "SIFS_BUNDLED", tmp_path / "missing-sifs")
    monkeypatch.delenv("SIFS_BIN", raising=False)
    result = code_search("SELECT id FROM users", ".", workdir=tmp_path)
    assert "fell back" not in result
    assert "app/db.py:9-13" in result


def test_code_search_auto_prefers_sifs(tmp_path, monkeypatch):
    from shlepa_agent import code_search as cs

    make_corpus(tmp_path)
    stub = make_stub(tmp_path)
    monkeypatch.setattr(cs, "SIFS_BUNDLED", stub)
    monkeypatch.delenv("SIFS_BIN", raising=False)
    result = code_search("SELECT id FROM users", ".", workdir=tmp_path)
    assert result.startswith("sifs[bm25]:")


def test_code_search_sifs_hybrid_passes_mode(tmp_path, monkeypatch):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path, record_argv=True)
    argv_file = tmp_path / "argv.txt"
    monkeypatch.setenv("SIFS_STUB_ARGV_FILE", str(argv_file))
    result = code_search(
        "SELECT id FROM users", ".", workdir=tmp_path,
        engine="sifs-hybrid", sifs_bin=str(stub),
    )
    assert "sifs[hybrid]:" in result
    argv = argv_file.read_text().split()
    assert "--mode" in argv
    assert argv[argv.index("--mode") + 1] == "hybrid"
    assert "--offline" in argv
    assert "--no-cache" in argv
    # Regression: --json must stay an option, not leak past "--" into the
    # query position (clap would then print human-formatted text).
    assert "--" in argv
    assert argv.index("--json") < argv.index("--")


def test_file_outline_sifs_symbols(tmp_path):
    make_corpus(tmp_path)
    stub = make_stub(tmp_path)
    result = file_outline(
        "app/routers/auth.py", workdir=tmp_path,
        engine="sifs", sifs_bin=str(stub),
    )
    assert "app/routers/auth.py (23 lines)" in result
    assert "8-21  def login" in result
    assert "22-23  def logout" in result
    # Envelope fields stripped.
    assert "\"symbols\"" not in result
    assert "\"confidence\"" not in result


def test_file_outline_sifs_missing_falls_back(tmp_path):
    make_corpus(tmp_path)
    result = file_outline(
        "app/routers/auth.py", workdir=tmp_path,
        engine="sifs", sifs_bin=str(tmp_path / "no-such-sifs"),
    )
    assert "fell back to regex" in result
    assert "def login(request):" in result
