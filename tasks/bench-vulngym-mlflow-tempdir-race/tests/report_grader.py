#!/usr/bin/env python3
"""Deterministic grader for the adapted VulnGym source-audit tasks."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

APP = Path(os.environ.get("BENCH_APP_DIR", "/app"))
TESTS = Path(os.environ.get("BENCH_TESTS_DIR", "/tests"))
REPORT = APP / "report.json"
EXPECTED = TESTS / "expected.json"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {path}: {exc}")


def line_span(value: object) -> tuple[int, int]:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value, value
    if isinstance(value, str):
        match = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+)\s*)?", value)
        if match:
            start = int(match.group(1))
            end = int(match.group(2) or start)
            if 0 < start <= end:
                return start, end
    raise ValueError(f"invalid line value: {value!r}")


def same_location(actual: object, expected: dict[str, object]) -> bool:
    if not isinstance(actual, dict) or actual.get("file") != expected["file"]:
        return False
    try:
        a0, a1 = line_span(actual.get("line"))
    except ValueError:
        return False
    e0, e1 = int(expected["start"]), int(expected["end"])
    tolerance = int(expected.get("tolerance", 0))
    return a1 >= e0 - tolerance and a0 <= e1 + tolerance


def main() -> None:
    report = load_json(REPORT)
    expected = load_json(EXPECTED)
    if not isinstance(report, dict) or not isinstance(expected, dict):
        fail("report and expected data must be JSON objects")

    if report.get("vulnerability_found") is not True:
        fail("vulnerability_found must be true")

    kind = report.get("vulnerability_type")
    if not isinstance(kind, str):
        fail("vulnerability_type must be a string")
    normalized_kind = kind.casefold()
    aliases = expected.get("type_aliases", [])
    if not any(str(alias).casefold() in normalized_kind for alias in aliases):
        fail("vulnerability_type does not identify the expected defect class")

    severity = report.get("severity")
    if not isinstance(severity, str) or severity.casefold() not in expected["severities"]:
        fail(f"unexpected severity: {severity!r}")

    if not same_location(report.get("entry_point"), expected["entry_point"]):
        fail("entry_point does not locate the vulnerable input/control-flow entry")
    if not same_location(report.get("critical_operation"), expected["critical_operation"]):
        fail("critical_operation does not locate the root-cause operation")

    flow = report.get("data_flow")
    if not isinstance(flow, list) or len(flow) < int(expected["minimum_flow_nodes"]):
        fail("data_flow is missing or too short")
    for landmark in expected["flow_landmarks"]:
        if not any(same_location(node, landmark) for node in flow):
            fail(f"data_flow misses landmark {landmark['file']}:{landmark['start']}")

    for field in ("root_cause", "impact", "recommendation"):
        value = report.get(field)
        if not isinstance(value, str) or len(value.strip()) < 40:
            fail(f"{field} must be a substantive explanation")

    allowed = {
        "vulnerability_found", "vulnerability_type", "severity", "entry_point",
        "critical_operation", "data_flow", "root_cause", "impact", "recommendation",
    }
    extra = set(report) - allowed
    if extra:
        fail(f"unexpected report keys: {sorted(extra)}")

    for relative, digest in expected["source_sha256"].items():
        path = APP / relative
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            fail(f"source fixture missing: {relative}: {exc}")
        if actual != digest:
            fail(f"source fixture was modified: {relative}")

    print("PASS: report identifies and traces the expected vulnerability")


if __name__ == "__main__":
    main()
