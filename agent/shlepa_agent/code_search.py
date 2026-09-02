"""Compact code-search primitives for the agent (rg engine + file_outline).

This module implements the compact search primitive behind the
``code_search`` / ``file_outline`` agent tools (wired as Tool records in
``shlepa_agent/tools/`` behind the ``AGENT_CODE_SEARCH`` env var; see the
code-search-tools plan). Two engines:

- ``rg``: wraps the preinstalled ripgrep (fixed-string pattern mode, no
  ranking), plus a regex ``file_outline`` scan;
- ``sifs``: the bundled SIFS binary (``tools/bin/sifs``), BM25-offline mode
  (``sifs-hybrid`` needs the embedding model and is dev-only). The SIFS JSON
  envelope is stripped and re-emitted in the same compact shape as the rg
  engine. A missing or broken SIFS binary degrades to the rg/regex engine
  (never crash).

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
import os
import re
import shutil
import subprocess
from pathlib import Path

#: Hard wall for one search call (a search must finish well under the phase
#: caps even on 10k-file corpora).
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


#: Pinned SIFS version. Keep in sync with agent/tools/bin/PROVENANCE.md and
#: the CRATE pin in agent/tools/bin/rebuild-sifs.sh. On a mismatch the tool
#: output carries a warning line (the run continues).
SIFS_PINNED_VERSION = "0.4.0"

#: Hard wall for one sifs call (cold index + query). Matches the 30s bash
#: cap of the v5 regime.
SIFS_TIMEOUT_SEC = 30.0

#: Dev-only env override for the bundled SIFS binary path.
SIFS_BIN_ENV = "SIFS_BIN"

#: Bundled binary, relative to this file. Resolves to agent/tools/bin/sifs
#: in the repo, tools/bin/sifs in the submission zip, and /agent/tools/bin/
#: sifs in the dev image (the same package + tools/ layout everywhere).
SIFS_BUNDLED = Path(__file__).resolve().parent.parent / "tools" / "bin" / "sifs"

#: Per-process cache of the one-shot ``sifs --version`` check:
#: binary path -> "" (pinned) or the warning line to prepend.
_SIFS_VERSION_CACHE: dict[str, str] = {}


def _resolve_sifs(
    sifs_bin: str | None,
) -> tuple[str | None, str | None]:
    """Locate the SIFS binary: explicit arg > $SIFS_BIN > bundled.

    Returns ``(path, missing_note)``; ``path`` is None when absent.
    """
    if sifs_bin:
        if os.path.isfile(sifs_bin) and os.access(sifs_bin, os.X_OK):
            return sifs_bin, None
        return None, f"sifs binary not found at explicit path {sifs_bin}"
    env_bin = os.environ.get(SIFS_BIN_ENV)
    if env_bin:
        if os.path.isfile(env_bin) and os.access(env_bin, os.X_OK):
            return env_bin, None
        return None, f"sifs binary not found at ${SIFS_BIN_ENV} ({env_bin})"
    if SIFS_BUNDLED.is_file():
        return str(SIFS_BUNDLED), None
    return None, "bundled sifs binary not present"


def _sifs_version_warning(sifs_bin: str) -> str:
    """Cached one-shot ``sifs --version`` check against the pin.

    Returns "" when the version matches (or the check fails), else a
    warning line to prepend to the tool output. Never raises.
    """
    if sifs_bin in _SIFS_VERSION_CACHE:
        return _SIFS_VERSION_CACHE[sifs_bin]
    warning = ""
    try:
        proc = subprocess.run(
            [sifs_bin, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        lines = (proc.stdout or "").strip().splitlines()
        version = lines[0].split()[-1] if lines and proc.returncode == 0 else ""
        if version and version != SIFS_PINNED_VERSION:
            warning = (
                f"WARNING: sifs version {version} differs from the pinned "
                f"{SIFS_PINNED_VERSION} (agent/tools/bin/PROVENANCE.md)\n"
            )
    except (OSError, subprocess.SubprocessError):
        warning = ""
    _SIFS_VERSION_CACHE[sifs_bin] = warning
    return warning


def _run_sifs(
    sifs_bin: str, args: list[str], cwd: Path | None = None
) -> tuple[dict | None, str]:
    """Run one sifs subcommand with ``--json`` and parse the JSON object.

    ``--json`` is inserted before any ``--`` separator, so flags never
    leak into trailing positional arguments (e.g. a search query). Returns
    ``(parsed, status)`` where status is "ok", "timeout", or
    "error:<short reason>". Never raises.
    """
    if "--" in args:
        sep = args.index("--")
        cmd = [sifs_bin, *args[:sep], "--json", "--", *args[sep + 1:]]
    else:
        cmd = [sifs_bin, *args, "--json"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=SIFS_TIMEOUT_SEC,
            cwd=str(cwd) if cwd is not None else None,
        )
    except FileNotFoundError:
        return None, "error:sifs executable disappeared"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as exc:
        return None, f"error:{exc.__class__.__name__}"
    if proc.returncode != 0:
        tail = [
            ln
            for ln in (proc.stderr or proc.stdout or "").strip().splitlines()
            if ln.strip()
        ]
        return None, "error:" + (tail[-1][:120] if tail else f"exit {proc.returncode}")
    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, "error:sifs output is not valid JSON"
    if not isinstance(data, dict):
        return None, "error:sifs JSON is not an object"
    return data, "ok"


def _sifs_symbol_label(result: dict) -> str:
    """Best-effort enclosing-symbol label for one sifs chunk.

    Prefers a definition-role symbol ("def login"), then any symbol, then
    the first breadcrumb. Mirrors the rg engine's header annotation.
    """
    symbols = result.get("symbols") or []
    for sym in symbols:
        if isinstance(sym, dict) and sym.get("role") == "definition" and sym.get("name"):
            return f"{sym.get('kind', '')} {sym['name']}".strip()
    if symbols and isinstance(symbols[0], dict) and symbols[0].get("name"):
        return f"{symbols[0].get('kind', '')} {symbols[0]['name']}".strip()
    crumbs = result.get("breadcrumbs") or []
    return crumbs[0] if isinstance(crumbs, list) and crumbs else ""


def _sifs_entry(idx: int, rel: str, result: dict) -> str:
    """One ranked sifs chunk in the same compact shape as an rg window."""
    w0 = int(result.get("start_line") or 1)
    w1 = max(w0, int(result.get("end_line") or w0))
    head = f"{idx}. {rel}:{w0}-{w1}"
    label = _sifs_symbol_label(result)
    if label:
        head += f"  ({label})"
    body = [head]
    for i, line in enumerate((result.get("content") or "").splitlines()):
        n = w0 + i
        if n > w1:
            break
        body.append(f"{n:>6}: {line}")
    return "\n".join(body) + "\n"


def _search_sifs(
    sifs_bin: str,
    query: str,
    target: Path,
    *,
    limit: int,
    max_tokens: int,
    mode: str,
) -> tuple[str | None, str]:
    """SIFS search; returns ``(text, status)``.

    Strips the JSON envelope (score/symbols/breadcrumbs/index_stats inflate
    2-3x over the token budget, see research/code_search/analysis/
    fit-matrix.md) and re-emits the rg engine's compact shape: ranked
    chunks grouped per file, strict token budget, truncation marker. The
    index is rebuilt per call (``--no-cache``) so the tool is stateless.
    """
    data, status = _run_sifs(
        sifs_bin,
        [
            "search",
            "--source",
            str(target),
            "--mode",
            mode,
            "--offline",
            "--no-cache",
            "--limit",
            str(max(1, limit * MAX_WINDOWS_PER_FILE)),
            "--",
            query,
        ],
    )
    if status != "ok":
        return None, status
    results = data.get("results") or []
    if not results:
        return f"code_search: no matches for {query.strip()!r} under {target}", "no_match"

    by_file: dict[str, list[dict]] = {}
    total = 0
    for res in results:
        if not isinstance(res, dict):
            continue
        rel = res.get("file_path")
        if not rel:
            continue
        total += 1
        bucket = by_file.setdefault(str(rel), [])
        if len(bucket) < MAX_WINDOWS_PER_FILE:
            bucket.append(res)

    budget_chars = max(0, int(max_tokens) * CHARS_PER_TOKEN)
    if budget_chars <= 0:
        return "", "ok"
    if budget_chars < 20:
        return "...", "ok"

    entries: list[str] = []
    for rel, chunks in by_file.items():
        for res in chunks:
            entries.append(_sifs_entry(len(entries) + 1, rel, res))

    header = f"sifs[{mode}]: {query.strip()[:32]} in {str(target)[-32:]}\n"
    summary = f"{total} chunk(s) in {len(by_file)} file(s)\n"
    for k in range(len(entries), -1, -1):
        omitted = len(entries) - k
        text = header + "".join(entries[:k])
        if omitted:
            text += f"... [truncated: ~{max_tokens} tok, {omitted} more]\n"
        else:
            text += summary
        if len(text) <= budget_chars:
            return text, "ok"
    return "..."[:budget_chars], "ok"


def _outline_sifs(
    sifs_bin: str, file_path: Path, path_label: str, max_symbols: int
) -> tuple[str | None, str]:
    """SIFS outline of one file; returns ``(text, status)``.

    Runs ``sifs outline`` from the file's parent directory with the bare
    file name (sifs rejects absolute paths). Never raises.
    """
    try:
        line_count = len(
            file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        )
    except OSError as exc:
        return None, f"error:{exc.__class__.__name__}"
    data, status = _run_sifs(
        sifs_bin, ["outline", file_path.name, "--offline", "--no-cache"],
        cwd=file_path.parent,
    )
    if status != "ok":
        return None, status
    outline = data.get("outline")
    if not isinstance(outline, dict):
        return None, "error:sifs outline is missing"
    symbols = [
        s for s in (outline.get("symbols") or [])
        if isinstance(s, dict) and s.get("name")
    ]
    out = [f"{path_label} ({line_count} lines)\n"]
    shown = 0
    for sym in symbols:
        if shown >= max_symbols:
            break
        start = int(sym.get("line") or 0)
        end = int(sym.get("end_line") or start)
        out.append(
            f"  {start}-{end}  {sym.get('kind', '')} {sym['name']}".strip() + "\n"
        )
        shown += 1
    if len(symbols) > max_symbols:
        out.append(f"... [{len(symbols) - max_symbols} more symbols not shown]\n")
    if not symbols:
        out.append("  (no symbols found)\n")
    return "".join(out), "ok"


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
    engine: str | None = None,
    sifs_bin: str | None = None,
) -> str:
    """Search for code under ``path``; return compact ranked windows.

    Engines: "rg" (fixed-string ripgrep scan), "sifs" (bundled SIFS
    BM25-offline), "sifs-hybrid" (SIFS hybrid; needs the embedding model,
    dev-only), or None/"auto" (SIFS when the binary is present, else rg).
    A missing or broken SIFS binary degrades to the rg engine (an explicit
    engine logs a NOTE line; auto is silent). Files are ranked, at most
    ``limit`` files shown, each with up to MAX_WINDOWS_PER_FILE windows;
    the returned text always stays within ``max_tokens * 4`` characters
    (chars/4 token estimate) with a truncation marker. Never raises.
    """
    if not query or not query.strip():
        return "code_search: empty query"
    target = _resolve(path, workdir)
    if not target.exists():
        return f"code_search: path not found: {target}"
    eng = (engine or "auto").strip().lower()
    if eng not in ("auto", "rg", "sifs", "sifs-hybrid"):
        return (
            f"code_search: unknown engine {engine!r} "
            "(use rg, sifs, sifs-hybrid, or auto)"
        )
    if eng == "rg":
        return _search_rg(query, target, limit, context_lines, max_tokens, rg_bin)
    if eng in ("auto", "sifs", "sifs-hybrid"):
        bin_path, missing_note = _resolve_sifs(sifs_bin)
        if bin_path is not None:
            mode = "hybrid" if eng == "sifs-hybrid" else "bm25"
            out, sifs_status = _search_sifs(
                bin_path, query, target,
                limit=limit, max_tokens=max_tokens, mode=mode,
            )
            if sifs_status in ("ok", "no_match"):
                warn = _sifs_version_warning(bin_path)
                return (warn + out) if warn else out
            rg_out = _search_rg(query, target, limit, context_lines, max_tokens, rg_bin)
            if eng == "auto":
                return rg_out
            return f"NOTE: sifs {sifs_status}; fell back to rg\n" + rg_out
        if eng != "auto":
            return f"NOTE: {missing_note}; fell back to rg\n" + _search_rg(
                query, target, limit, context_lines, max_tokens, rg_bin
            )
    return _search_rg(query, target, limit, context_lines, max_tokens, rg_bin)


def _search_rg(
    query: str,
    target: Path,
    limit: int,
    context_lines: int,
    max_tokens: int,
    rg_bin: str | None = None,
) -> str:
    """The ripgrep engine (fixed-string scan, no ranking). Never raises."""
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
    engine: str | None = None,
    sifs_bin: str | None = None,
) -> str:
    """List def/class/func symbols of one file with line ranges.

    Engines: "sifs" (bundled SIFS outline), "regex" (Python regex scan),
    or None/"auto" (SIFS when the binary is present, else regex). A
    missing or broken SIFS binary degrades to the regex scan (an explicit
    engine logs a NOTE line; auto is silent). Ranges run from the symbol's
    start line to the line before the next symbol (or EOF) in the regex
    engine; sifs reports its own end lines. Never raises.
    """
    file_path = _resolve(path, workdir)
    if not file_path.exists():
        return f"file_outline: file not found: {file_path}"
    if not file_path.is_file():
        return f"file_outline: not a file: {file_path}"
    eng = (engine or "auto").strip().lower()
    if eng not in ("auto", "sifs", "regex"):
        return f"file_outline: unknown engine {engine!r} (use sifs, regex, or auto)"
    if eng != "regex":
        bin_path, missing_note = _resolve_sifs(sifs_bin)
        if bin_path is not None:
            out, sifs_status = _outline_sifs(bin_path, file_path, path, max_symbols)
            if sifs_status == "ok":
                warn = _sifs_version_warning(bin_path)
                return (warn + out) if warn else out
            if eng == "auto":
                return _outline_regex(file_path, path, max_symbols)
            return (
                f"NOTE: sifs {sifs_status}; fell back to regex\n"
                + _outline_regex(file_path, path, max_symbols)
            )
        if eng != "auto":
            return (
                f"NOTE: {missing_note}; fell back to regex\n"
                + _outline_regex(file_path, path, max_symbols)
            )
    return _outline_regex(file_path, path, max_symbols)


def _outline_regex(file_path: Path, path_label: str, max_symbols: int) -> str:
    """The regex-scan outline engine (def/class/func keyword match)."""
    try:
        size = file_path.stat().st_size
        if size > MAX_WINDOW_FILE_BYTES:
            return (
                f"file_outline: file too large ({size // (1024 * 1024)} MB); "
                f"use bash: grep -nE 'def |class |func ' {path_label} | head"
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

    out = [f"{path_label} ({len(lines)} lines)\n"]
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
