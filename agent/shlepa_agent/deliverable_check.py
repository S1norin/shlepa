"""Mechanical deliverable check (v6, w2-1).

A pure function over the task workdir: given a deliverable path and an
artifact spec (kind / format / keys / expected_content) it computes five
booleans -- exists, non_empty, parse_ok, keys_ok, valid -- with no LLM, no
subprocess, no network: file reads only.

The check is the harness-side oracle of the redesigned REVIEW
(docs/plans/agent-v6-review-redesign.md): it triggers the salvage route
(missing/empty deliverable after WORK), feeds the VERIFY context packet,
re-checks REPAIR mutations, and tracks the best artifact at exit. The
contest's own check remains authoritative; this is the harness's cheap
proxy for it.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .log import _log_event

#: deliverable kinds (mirrors artifact_spec.kind emitted by PLAN)
KINDS = ("file", "test_command", "answer")


@dataclass(frozen=True)
class ArtifactSpec:
    """Harness-side artifact spec.

    PLAN emits the pydantic twin in outputs.py; the runner converts it
    with :meth:`from_any`.
    """

    kind: str = "file"  # file | test_command | answer
    path: str = ""  # deliverable path ("" = not named)
    format: str = ""  # json | csv | patch | text ("" = unknown)
    keys: tuple[str, ...] = ()  # required top-level JSON keys / CSV columns
    expected_content: str | None = None  # verbatim content quoted from the instruction

    @classmethod
    def from_any(cls, spec: Any) -> ArtifactSpec | None:
        """Build from a dataclass / pydantic model / dict / None."""
        if spec is None:
            return None
        if isinstance(spec, cls):
            return spec
        if isinstance(spec, dict):
            data: dict[str, Any] = dict(spec)
        elif hasattr(spec, "model_dump"):
            data = spec.model_dump()
        else:
            data = {}
        keys = data.get("keys") or []
        if isinstance(keys, str):
            keys = [keys]
        return cls(
            kind=str(data.get("kind") or "file"),
            path=str(data.get("path") or ""),
            format=str(data.get("format") or ""),
            keys=tuple(str(k) for k in keys),
            expected_content=data.get("expected_content"),
        )


@dataclass(frozen=True)
class SinkCheck:
    """Per-task sink-keyword spec (#128), from task.toml [deliverable_check].

    For coordinate-style audit reports: the reported coordinate (the
    report's ``field`` — default ``critical_operation``, ``{file, line}``
    with ``line`` an int or an inclusive ``start-end`` span) is expanded by
    ``tolerance`` lines on each side, and that window must contain at least
    one match of ``keywords`` (a regex pattern). Keyword maps live in task
    metadata, never in agent code.
    """

    keywords: str  # regex pattern, case-insensitive
    field: str = "critical_operation"  # report key holding {file, line}
    tolerance: int = 2  # lines to expand on each side of the coordinate

    @classmethod
    def from_any(cls, value: Any) -> "SinkCheck | None":
        """Build from a SinkCheck / dict / bare pattern string / None.

        Returns None when no usable spec is present (unset, no keywords,
        or an unrecognizable shape) — tasks without a keyword map are
        unaffected.
        """
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            value = {"keywords": value}
        if not isinstance(value, dict):
            return None
        keywords = str(value.get("keywords") or "").strip()
        if not keywords:
            return None
        try:
            tolerance = int(value.get("tolerance", cls.tolerance))
        except (TypeError, ValueError):
            tolerance = cls.tolerance
        return cls(
            keywords=keywords,
            field=str(value.get("field") or "critical_operation"),
            tolerance=max(0, tolerance),
        )


@dataclass(frozen=True)
class DeliverableCheck:
    """Five booleans + a one-line reason (the reason names the first failed check).

    ``sink_ok`` is True when no sink spec is configured (task without a
    keyword map) or the sink window matched (#128).
    """

    exists: bool
    non_empty: bool
    parse_ok: bool
    keys_ok: bool
    valid: bool
    reason: str = ""
    sink_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "exists": self.exists,
            "non_empty": self.non_empty,
            "parse_ok": self.parse_ok,
            "keys_ok": self.keys_ok,
            "valid": self.valid,
            "reason": self.reason,
            "sink_ok": self.sink_ok,
        }


def _parse_content(path: Path, fmt: str) -> tuple[bool, Any, str, str]:
    """Parse the file per format. Returns (parse_ok, parsed, raw, error)."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return False, None, "", f"read: {e}"
    fmt = (fmt or "").lower().strip()
    if fmt == "json":
        try:
            return True, json.loads(raw), raw, ""
        except (json.JSONDecodeError, ValueError) as e:
            return False, None, raw, f"json: {e}"
    if fmt == "csv":
        try:
            rows = [r for r in csv.reader(raw.splitlines()) if any(c.strip() for c in r)]
        except csv.Error as e:
            return False, None, raw, f"csv: {e}"
        if not rows:
            return False, None, raw, "csv: no rows"
        return True, rows, raw, ""
    if fmt == "patch":
        lines = raw.splitlines()
        if any(ln.startswith("---") for ln in lines) and any(
            ln.startswith("+++") for ln in lines
        ):
            return True, raw, raw, ""
        return False, None, raw, "patch: no unified-diff headers"
    # plain text / unknown format: a readable file is parseable
    return True, raw, raw, ""


def _keys_ok(parsed: Any, keys: tuple[str, ...], fmt: str) -> tuple[bool, str]:
    if not keys:
        return True, ""
    fmt = (fmt or "").lower().strip()
    if fmt == "json" or (fmt == "" and isinstance(parsed, (dict, list))):
        if not isinstance(parsed, dict):
            return False, f"top-level is {type(parsed).__name__}, keys need an object"
        missing = [k for k in keys if k not in parsed]
        return (not missing, f"missing keys: {', '.join(missing)}") if missing else (True, "")
    if fmt == "csv":
        first_row = parsed[0] if isinstance(parsed, list) and parsed else []
        header = [str(h).strip() for h in first_row]
        missing = [k for k in keys if k not in header]
        return (not missing, f"missing columns: {', '.join(missing)}") if missing else (True, "")
    return False, f"keys are checkable only for json/csv, not '{fmt}'"


def _content_ok(raw: str, expected_content: str | None) -> tuple[bool, str]:
    if expected_content is None:
        return True, ""
    if raw.strip() == expected_content.strip():
        return True, ""
    return False, "content does not match the expected_content quoted in the instruction"


def _line_window(
    line: Any, tolerance: int, n_lines: int
) -> tuple[int, int] | None:
    """Resolve an int / ``start-end`` line to an inclusive (start, end)
    expanded by ``tolerance`` on each side, clamped to [1, n_lines].
    None when the value is not a resolvable coordinate."""
    try:
        if isinstance(line, bool):
            return None
        if isinstance(line, int):
            start = end = line
        elif isinstance(line, str):
            text = line.strip()
            if "-" in text:
                a, _, b = text.partition("-")
                start, end = int(a), int(b)
            else:
                start = end = int(text)
        else:
            return None
    except (TypeError, ValueError):
        return None
    if start > end:
        start, end = end, start
    return max(1, start - tolerance), min(n_lines, end + tolerance)


def _sink_ok(parsed: Any, workdir: Path, sink: SinkCheck) -> tuple[bool, str]:
    """#128: does the reported coordinate window contain the expected sink?

    Reads the reported file under workdir (file reads only). Any
    structural problem (missing field, bad coordinate, missing file,
    invalid pattern) is a miss with an explicit reason — except an
    invalid keywords pattern, which skips the check entirely so a typo
    in task metadata can never block a run.
    """
    try:
        pattern = re.compile(sink.keywords, re.IGNORECASE)
    except re.error:
        return True, ""  # invalid pattern: skip (see docstring)
    node = parsed.get(sink.field) if isinstance(parsed, dict) else None
    if not isinstance(node, dict):
        return False, f"report has no usable '{sink.field}' coordinate"
    file_name = str(node.get("file") or "")
    if not file_name:
        return False, f"'{sink.field}' names no file"
    p = Path(file_name)
    if not p.is_absolute():
        p = workdir / p
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, f"reported file not found: {file_name}"
    lines = text.splitlines()
    window = _line_window(node.get("line"), sink.tolerance, len(lines))
    if window is None:
        return False, f"'{sink.field}' line is not a line or a start-end span"
    start, end = window
    segment = "\n".join(lines[start - 1 : end])
    if pattern.search(segment):
        return True, ""
    return (
        False,
        f"reported line {start}-{end} of {file_name} does not contain the "
        f"expected sink (keywords: {sink.keywords}) — check whether you "
        "traced the source side instead",
    )


def _check(
    workdir: Path | str, s: ArtifactSpec, sink: SinkCheck | None = None
) -> DeliverableCheck:
    workdir = Path(workdir)
    if not s.path:
        return DeliverableCheck(False, False, False, False, False, "no path in the spec")
    p = Path(s.path)
    if not p.is_absolute():
        p = workdir / p
    if not p.is_file():
        return DeliverableCheck(False, False, False, False, False, f"missing: {p}")
    if p.stat().st_size == 0:
        return DeliverableCheck(True, False, False, False, False, f"empty: {p}")
    parse_ok, parsed, raw, err = _parse_content(p, s.format)
    if not parse_ok:
        return DeliverableCheck(True, True, False, False, False, f"parse: {err}")
    if sink is not None:
        sink_ok, serr = _sink_ok(parsed, workdir, sink)
        if not sink_ok:
            return DeliverableCheck(
                True, True, True, False, False, f"sink: {serr}", sink_ok=False
            )
    keys_ok, kerr = _keys_ok(parsed, s.keys, s.format)
    if not keys_ok:
        return DeliverableCheck(True, True, True, False, False, f"keys: {kerr}")
    content_ok, cerr = _content_ok(raw, s.expected_content)
    if not content_ok:
        return DeliverableCheck(True, True, True, True, False, f"content: {cerr}")
    return DeliverableCheck(True, True, True, True, True, "")


def check_deliverable(
    workdir: Path | str,
    spec: ArtifactSpec | dict[str, Any] | Any,
    *,
    sink: SinkCheck | dict[str, Any] | str | None = None,
    log: bool = True,
) -> DeliverableCheck:
    """Mechanically check the deliverable at spec.path under workdir.

    File reads only -- no LLM, no subprocess, no network. ``sink`` is an
    optional per-task sink-keyword spec (#128); when set, the reported
    coordinate window must contain the expected sink. Logs one
    ``deliverable_check`` event (disable with ``log=False`` for pure use).
    """
    s = ArtifactSpec.from_any(spec) or ArtifactSpec()
    sink = SinkCheck.from_any(sink)
    result = _check(workdir, s, sink)
    if log:
        _log_event("deliverable_check", kind=s.kind, path=s.path, **result.to_dict())
    return result
