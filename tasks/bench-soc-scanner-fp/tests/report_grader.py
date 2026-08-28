#!/usr/bin/env python3
"""Grader for bench-soc-scanner-fp (SOCBench SCN-029, adapted).

Reads /app/report.json and exits 0 iff the report is a strict match for
the expected verdict fields:

  verdict              == FALSE_POSITIVE_AUTHORIZED_PENTEST
  flagged_source_ip    == 10.10.200.15
  within_approved_window is true (JSON boolean)

Exits 1 on any other outcome (missing file, invalid JSON, wrong fields).
"""

import json
import sys

REPORT = "/app/report.json"

EXPECTED = {
    "verdict": "FALSE_POSITIVE_AUTHORIZED_PENTEST",
    "flagged_source_ip": "10.10.200.15",
    "within_approved_window": True,
}

ALLOWED_KEYS = set(EXPECTED)


def main() -> int:
    try:
        with open(REPORT, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read {REPORT}: {exc}")
        return 1

    if not isinstance(report, dict):
        print("FAIL: report must be a JSON object")
        return 1

    extra = set(report) - ALLOWED_KEYS
    if extra:
        print(f"FAIL: unexpected keys: {sorted(extra)}")
        return 1

    for key, expected in EXPECTED.items():
        got = report.get(key)
        if isinstance(expected, bool):
            if not isinstance(got, bool) or got is not expected:
                print(f"FAIL: {key} = {got!r}, expected {expected!r}")
                return 1
        elif got != expected:
            print(f"FAIL: {key} = {got!r}, expected {expected!r}")
            return 1

    print("PASS: report matches expected verdict")
    return 0


if __name__ == "__main__":
    sys.exit(main())
