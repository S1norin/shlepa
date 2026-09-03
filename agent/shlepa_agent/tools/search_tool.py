"""Search tool: stdlib-only read-only grep / glob / ls over the task dir.

No ripgrep dependency (the submission environment is fixed: jq, python3,
ripgrep preinstalled but the agent must not add dependencies) — the walk
is pure stdlib. Read-only by construction: only file reads, no writes.

Output contract: a header with the TOTAL match count plus the first N
matches; the whole result is capped at 8 KB with a truncation note, so a
large corpus can never blow up the context (backlog #54 smart-grep).
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from fnmatch import fnmatch
from pathlib import Path

from pydantic_ai import RunContext

from shlepa_agent.log import _log_event
from shlepa_agent.tools.base import AgentDeps, Tool, format_tool_result, resolve_path

#: Hard char cap on the result body.
DEFAULT_MAX_OUTPUT = 8192

#: Wall budget for the directory walk; on expiry the tool returns what it
#: has so far with a note (the PLAN phase cannot wait for a slow scan).
WALK_DEADLINE_S = 10.0

#: Per-file caps: probe the head for a null byte (binary), skip files
#: larger than the size cap (one huge file must not eat the walk).
_BINARY_PROBE_BYTES = 8192
_MAX_FILE_BYTES = 2 * 1024 * 1024

#: Long match lines are cut in the output.
_LINE_EXCERPT = 200

#: Default number of matches shown (the total count is always reported).
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

#: Directories never worth scanning.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv"}


def _iter_files(root: Path, deadline: float) -> tuple[list[Path], bool]:
    """Collect files under ``root`` (os.walk order, skip dirs pruned),
    stopping after the deadline. Returns (files, stopped)."""
    files: list[Path] = []
    stopped = False
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for name in filenames:
            if time.monotonic() > deadline:
                stopped = True
                break
            files.append(Path(dirpath) / name)
        if stopped:
            break
    return files, stopped


def _is_binary(p: Path) -> bool:
    try:
        with p.open("rb") as fh:
            return b"\x00" in fh.read(_BINARY_PROBE_BYTES)
    except OSError:
        return True  # unreadable: treat as non-text, skip


def _grep(
    root: Path, pattern: str, is_regex: bool, limit: int, deadline: float
) -> tuple[int, list[str], bool]:
    files, stopped = _iter_files(root, deadline)
    rx = None
    if is_regex:
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ValueError(f"invalid regex {pattern!r}: {e}") from None
    total = 0
    shown: list[str] = []
    for f in files:
        try:
            if f.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        if _is_binary(f):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        for lineno, line in enumerate(text.splitlines(), start=1):
            hit = rx.search(line) if rx is not None else pattern in line
            if not hit:
                continue
            total += 1
            if len(shown) < limit:
                excerpt = line.strip()[:_LINE_EXCERPT]
                shown.append(f"{rel}:{lineno}: {excerpt}")
    return total, shown, stopped


def _glob(root: Path, pattern: str, limit: int, deadline: float) -> tuple[int, list[str], bool]:
    """List files whose path RELATIVE to root matches the glob pattern.

    A leading ``**/`` is optional (``**/*.py`` and ``*.py`` both work);
    plain names match at any depth, like ripgrep --glob-style discovery.
    """
    plain = pattern.removeprefix("**/")
    files, stopped = _iter_files(root, deadline)
    total = 0
    shown: list[str] = []
    for f in files:
        rel = f.relative_to(root).as_posix()
        if fnmatch(rel, pattern) or fnmatch(rel, plain):
            total += 1
            if len(shown) < limit:
                shown.append(rel)
    return total, shown, stopped


def _ls(p: Path, limit: int) -> tuple[int, list[str]]:
    entries: list[str] = []
    for name in sorted(p.iterdir()):
        entries.append(name.as_posix() + "/" if name.is_dir() else name.as_posix())
    return len(entries), entries[:limit]


async def search(
    ctx: "RunContext[AgentDeps]",
    mode: str = "grep",
    pattern: str = "",
    path: str = ".",
    is_regex: bool = False,
    limit: int = DEFAULT_LIMIT,
) -> str:
    """Search the task directory (read-only, stdlib only, capped output).
    Modes: "grep" — find lines containing pattern (substring; is_regex=true
    for regex) under path; "glob" — list files whose relative path matches
    the glob pattern (e.g. "*.json" or "**/*.py") under path; "ls" — list
    one directory (pattern is ignored). Returns the TOTAL match count plus
    the first ``limit`` matches (max 200); output capped at 8192 chars;
    large dirs are scanned for at most 10 s (partial results + a note).
    pattern is required for grep/glob; for ls pass path= the directory."""
    t0 = time.monotonic()
    scfg = ctx.deps.cfg.tools.search
    max_output = scfg.max_output or DEFAULT_MAX_OUTPUT
    if not pattern and mode != "ls":
        return format_tool_result(
            ctx, "search", "", t0, args={"mode": mode, "pattern": pattern, "path": path},
            failed="pattern is empty", untrusted=True,
        )
    if limit <= 0:
        limit = DEFAULT_LIMIT
    limit = min(limit, MAX_LIMIT)
    _log_event("tool_call", tool="search", mode=mode, pattern=pattern,
               path=path, is_regex=is_regex, limit=limit)

    def finish(
        body: str, *, note: str | None = None, failed: str | None = None
    ) -> str:
        return format_tool_result(
            ctx, "search", body, t0,
            args={"mode": mode, "pattern": pattern, "path": path},
            note=note, failed=failed, untrusted=True,
        )

    root = resolve_path(path, ctx.deps.workdir)
    if not root.exists():
        return finish("", failed=f"path not found: {path}")

    deadline = time.monotonic() + WALK_DEADLINE_S
    try:
        if mode == "grep":
            total, shown, stopped = await asyncio.to_thread(
                _grep, root, pattern, is_regex, limit, deadline
            )
            kind = "regex" if is_regex else "substring"
            header = (
                f"grep {pattern!r} ({kind}) under {path}: {total} total match(es), "
                f"showing first {len(shown)}"
            )
        elif mode == "glob":
            total, shown, stopped = await asyncio.to_thread(
                _glob, root, pattern, limit, deadline
            )
            header = (
                f"glob {pattern!r} under {path}: {total} file(s) total, "
                f"showing first {len(shown)}"
            )
        elif mode == "ls":
            if not root.is_dir():
                return finish("", failed=f"not a directory: {path}")
            total, shown = await asyncio.to_thread(_ls, root, limit)
            stopped = False  # single-directory listing: no walk to stop
            header = f"ls {path}: {total} entries, showing first {len(shown)}"
        else:
            return finish("", failed=f"unknown search mode: {mode!r} (use grep, glob or ls)")
    except ValueError as e:
        return finish("", failed=str(e))

    body = header + "\n" + "\n".join(shown) if shown else header + "\n<no matches>"
    notes = []
    if stopped:
        notes.append(f"scan stopped after {WALK_DEADLINE_S:.0f}s (partial results)")
    if len(shown) < total:
        notes.append(f"{total - len(shown)} more match(es) not shown")
    if len(body) > max_output:
        body = body[:max_output] + f"\n[...truncated to {max_output} chars]"
        notes.append("output truncated")
    _log_event("tool_result", tool="search", mode=mode, total=total, shown=len(shown))
    return finish(body, note=" | ".join(notes) or None)


SEARCH_TOOL = Tool(
    name="search",
    note=(
        "search: read-only stdlib search over the task dir (no bash needed "
        "for text/file discovery). mode='grep' (substring, or regex with "
        "is_regex=true) finds lines; mode='glob' lists files by pattern "
        "(e.g. '**/*.py'); mode='ls' lists one dir. pattern is required; "
        "path defaults to the task root. Reports the TOTAL count plus the "
        "first up-to-200 matches; output capped at 8192 chars; large dirs "
        "are scanned for at most 10 s."
    ),
    run=search,
)
