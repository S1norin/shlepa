"""Compact code-search primitives for the agent (rg engine + file_outline).

This module implements the compact search primitive behind the
``code_search`` / ``file_outline`` agent tools (wired as Tool records in
``shlepa_agent/tools/`` behind the ``AGENT_CODE_SEARCH`` env var; see the
code-search-tools plan). The ``rg`` engine
wraps the preinstalled ripgrep (fixed-string pattern mode, no ranking); a
SIFS BM25 engine emitting the same shape is added to this module later.

Output shape (compact text, not JSON — the SIFS JSON envelope inflates 2-3x
over its token budget, see research/code_search/analysis/fit-matrix.md):

    1. app/db.py:11-15  (def get_pool():)
         11: def get_pool():
         12:     conn = sqlite3.connect(DB_PATH)

- per-file grouped match windows, merged across a context gap
- ``file:line-range`` header + best-effort enclosing-symbol annotation
- deduped match lines, strict token budget (chars/4 estimate) with a
  truncation marker

All public functions are plain (sync) and NEVER raise: every failure
(missing rg, bad path, timeout, unreadable file) returns a compact error
string the agent can react to — the "never crash" philosophy of the
runner. Tool wiring adapts them to Tool records via asyncio.to_thread.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

#: Hard wall for one search call (the bash tool is capped at 120s; a search
#: must finish well under that even on 10k-file corpora).
RG_TIMEOUT_SEC = 60.0

#: Global cap on matches consumed from rg (protects pathological queries).
MAX_MATCHES = 1000

#: Per-file match cap passed to rg.
RG_MAX_COUNT = 200

#: Max windows per file (earliest matches first).
MAX_WINDOWS_PER_FILE = 3

#: Files larger than this get bare match lines, no window content.
MAX_WINDOW_FILE_BYTES = 4 * 1024 * 1024

#: chars/4 token estimate (repo-wide convention).
CHARS_PER_TOKEN = 4

#: Max symbols listed by file_outline before a truncation marker.
MAX_OUTLINE_SYMBOLS = 200

#: Best-effort enclosing-symbol scan for window headers: top-level-ish
#: declaration keywords only, deliberately conservative to avoid noise.
_ENCLOSING_SYMBOL_RE = re.compile(
    r"^\s*(?:"
    r"(?:export\s+)?(?:async\s+)?function"
    r"|(?:async\s+)?def"
    r"|(?:class|struct|enum|trait|interface)\s+\w"
    r"|(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?fn"
    r"|\btype\s+\w+\s*(?:struct|interface)"
    r"|\bfunc\b"
    r")"
)

#: def/class/func scan for file_outline (same conservative keyword set).
_SYMBOL_RE = re.compile(
    r"^\s*(?:"
    r"(?:export\s+)?(?:async\s+)?function\s*\*?\s*\w*"
    r"|(?:async\s+)?def\s+\w*"
    r"|(?:class|struct|enum|trait|interface)\s+\w*"
    r"|(?:pub\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+\w*"
    r"|\bfunc\s*(?:\([^)]*\))?\s*\w*"
    r"|\btype\s+\w*\s*(?:struct|interface)"
    r")"
)


def _resolve(path: str, workdir: Path | None) -> Path:
    p = Path(path)
    if not p.is_absolute() and workdir is not None:
        p = workdir / p
    return p.resolve()


def _run_rg(
    rg_bin: str, query: str, target: Path
) -> tuple[dict[str, dict[int, str]], str]:
    """Run ``rg --json -F -n`` and collect per-file match lines.

    Returns ``({path_text: {line_number: line_text}}, status)`` where status
    is "ok", "no_match", "timeout", or "error:<short reason>". Never raises.
    """
    cmd = [
        rg_bin,
        "--json",
        "-F",
        "-n",
        "--max-count",
        str(RG_MAX_COUNT),
        "--",
        query,
        str(target),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RG_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return {}, "error:rg executable disappeared"
    except subprocess.TimeoutExpired:
        return {}, "timeout"
    except OSError as exc:
        return {}, f"error:{exc.__class__.__name__}"
    if proc.returncode not in (0, 1):
        tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        return {}, "error:" + (tail[-1][:120] if tail else f"exit {proc.returncode}")
    per_file: dict[str, dict[int, str]] = {}
    total = 0
    for line in proc.stdout.splitlines():
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if ev.get("type") != "match":
            continue
        data = ev.get("data") or {}
        path_text = (data.get("path") or {}).get("text")
        line_no = data.get("line_number")
        if not path_text or line_no is None:
            continue
        total += 1
        if total > MAX_MATCHES:
            break
        lines_text = (data.get("lines") or {}).get("text") or ""
        per_file.setdefault(path_text, {}).setdefault(int(line_no), lines_text.rstrip("\n"))
    if not per_file:
        return per_file, "no_match"
    return per_file, "ok"


def _merge_windows(
    line_nos: list[int], context_lines: int, file_lines: int
) -> list[tuple[int, int]]:
    """Merge 1-based match line numbers into inclusive (start, end) windows."""
    raw: list[tuple[int, int]] = []
    start = end = None
    for ln in line_nos:
        if start is None:
            start = end = ln
        elif ln - end <= 2 * context_lines + 1:
            end = ln
        else:
            raw.append((start, end))
            start = end = ln
    if start is not None:
        raw.append((start, end))
    windows: list[tuple[int, int]] = []
    for s, e in raw:
        w0 = max(1, s - context_lines)
        w1 = min(file_lines, e + context_lines)
        if windows and w0 <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], w1))
        else:
            windows.append((w0, w1))
    return windows


def _read_lines(file_path: Path) -> list[str] | None:
    try:
        if file_path.stat().st_size > MAX_WINDOW_FILE_BYTES:
            return None
        return file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def _enclosing_symbol(lines: list[str], window_start: int) -> str:
    """Nearest declaration keyword at or above window_start (1-based)."""
    for i in range(window_start - 1, -1, -1):
        if _ENCLOSING_SYMBOL_RE.match(lines[i]):
            return lines[i].strip()[:60]
    return ""


def _format_entry(idx: int, rel: str, w0: int, w1: int, lines: list[str]) -> str:
    head = f"{idx}. {rel}:{w0}-{w1}"
    symbol = _enclosing_symbol(lines, w0)
    if symbol:
        head += f"  ({symbol})"
    body = [head]
    for n in range(w0, w1 + 1):
        body.append(f"{n:>6}: {lines[n - 1]}")
    return "\n".join(body) + "\n"


def code_search(
    query: str,
    path: str = ".",
    *,
    limit: int = 5,
    context_lines: int = 3,
    max_tokens: int = 1500,
    workdir: Path | None = None,
    rg_bin: str | None = None,
) -> str:
    """Search for a fixed string under ``path``; return compact windows.

    Files are ranked by match count (most first, then path); at most
    ``limit`` files are shown, each with up to MAX_WINDOWS_PER_FILE merged
    windows. The returned text always stays within ``max_tokens * 4``
    characters (chars/4 token estimate); a truncation marker is present
    when results were dropped. Never raises.
    """
    if not query or not query.strip():
        return "code_search: empty query"
    target = _resolve(path, workdir)
    if not target.exists():
        return f"code_search: path not found: {target}"
    rg = rg_bin or shutil.which("rg")
    if rg is None:
        return (
            "code_search: ripgrep (rg) not found in PATH; "
            f"fallback: use bash: grep -rn {query.strip()!r} {target}"
        )
    per_file, status = _run_rg(rg, query, target)
    if status == "no_match":
        return f"code_search: no matches for {query.strip()!r} under {target}"
    if status == "timeout":
        return f"code_search: timed out after {RG_TIMEOUT_SEC:.0f}s scanning {target}"
    if status != "ok":
        return f"code_search: {status} (scanning {target})"

    ranked = sorted(per_file.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    budget_chars = max(0, int(max_tokens) * CHARS_PER_TOKEN)
    if budget_chars <= 0:
        return ""
    if budget_chars < 20:
        return "..."

    entries: list[str] = []
    shown_files = 0
    match_count = 0
    for rel, by_line in ranked:
        if shown_files >= limit:
            break
        shown_files += 1
        file_path = Path(rel) if Path(rel).is_absolute() else target / rel
        match_count += len(by_line)
        line_nos = sorted(by_line)
        lines = _read_lines(file_path)
        if lines is None:
            # Too large for windowing: bare match lines.
            for ln in line_nos[:10]:
                entries.append(f"{rel}:{ln}: {by_line[ln]}\n")
            if len(line_nos) > 10:
                entries.append(f"{rel}: ... {len(line_nos) - 10} more match lines\n")
            continue
        for w0, w1 in _merge_windows(line_nos, context_lines, len(lines))[
            :MAX_WINDOWS_PER_FILE
        ]:
            entries.append(_format_entry(len(entries) + 1, rel, w0, w1, lines))

    header = f"rg: {query.strip()[:32]} in {str(target)[-32:]}\n"
    summary = f"{match_count} match(es) in {shown_files} file(s)\n"
    for k in range(len(entries), -1, -1):
        omitted = len(entries) - k
        text = header + "".join(entries[:k])
        if omitted:
            text += f"... [truncated: ~{max_tokens} tok, {omitted} more]\n"
        else:
            text += summary
        if len(text) <= budget_chars:
            return text
    return "..."[:budget_chars]


def file_outline(
    path: str,
    *,
    workdir: Path | None = None,
    max_symbols: int = MAX_OUTLINE_SYMBOLS,
) -> str:
    """List def/class/func symbols of one file with line ranges.

    Ranges run from the symbol's start line to the line before the next
    symbol (or EOF). Never raises.
    """
    file_path = _resolve(path, workdir)
    if not file_path.exists():
        return f"file_outline: file not found: {file_path}"
    if not file_path.is_file():
        return f"file_outline: not a file: {file_path}"
    try:
        size = file_path.stat().st_size
        if size > MAX_WINDOW_FILE_BYTES:
            return (
                f"file_outline: file too large ({size // (1024 * 1024)} MB); "
                f"use bash: grep -nE 'def |class |func ' {path} | head"
            )
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"file_outline: unreadable ({exc.__class__.__name__})"

    symbols: list[tuple[int, str]] = []
    for i, line in enumerate(lines, start=1):
        if _SYMBOL_RE.match(line):
            symbols.append((i, line.strip()[:60]))
        if len(symbols) > max_symbols:
            break

    out = [f"{path} ({len(lines)} lines)\n"]
    shown = 0
    for idx, (start, label) in enumerate(symbols):
        if shown >= max_symbols:
            break
        end = symbols[idx + 1][0] - 1 if idx + 1 < len(symbols) else len(lines)
        out.append(f"  {start}-{end}  {label}\n")
        shown += 1
    if len(symbols) > max_symbols:
        out.append(f"... [{len(symbols) - max_symbols} more symbols not shown]\n")
    if not symbols:
        out.append("  (no def/class/func symbols found)\n")
    return "".join(out)
