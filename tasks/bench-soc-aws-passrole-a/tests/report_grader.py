#!/usr/bin/env python3
"""Grader for bench-soc-aws-passrole-a (SOCBench SCN-023, adapted).

Reads /app/report.json and exits 0 iff:

  verdict                    == TRUE_POSITIVE_INCIDENT
  primary_mitre_technique    contains one of T1098.003, T1078.004
  compromised_hosts          normalizes to exactly {'ws-fin-10'}
  compromised_accounts       normalizes to exactly {'s.garcia'}
  key_indicators             >= 2 strings, each appearing verbatim in the
                             evidence, with >= 2 distinct hits in
                             passrole, adminrole, 45.33.32.156, python-requests

Exits 1 on any other outcome (missing file, invalid JSON, wrong fields).
"""

import json
import sys
from pathlib import Path

REPORT = "/app/report.json"
EVIDENCE_DIR = Path("/app/evidence")

ALLOWED_KEYS = {
    "verdict",
    "primary_mitre_technique",
    "compromised_hosts",
    "compromised_accounts",
    "key_indicators",
}

EXPECTED_VERDICT = "TRUE_POSITIVE_INCIDENT"
REQUIRED_MITRE = ['T1098.003', 'T1078.004']
REQUIRED_HOSTS = {'ws-fin-10'}
REQUIRED_ACCOUNTS = {'s.garcia'}
IOC_KEYWORDS = {'45.33.32.156', 'adminrole', 'passrole', 'python-requests'}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def norm_host(value: str) -> str:
    v = value.strip().lower().rstrip(".")
    if v.endswith(".corp.local"):
        v = v[: -len(".corp.local")]
    return v


def norm_account(value: str) -> str:
    return value.strip().lower().split("@", 1)[0]


def evidence_strings() -> list[str]:
    """All string leaves of every evidence JSONL event (verbatim values)."""
    out: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        else:
            out.append(str(node))

    for path in sorted(EVIDENCE_DIR.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                walk(json.loads(line))
    return out


def main() -> None:
    try:
        with open(REPORT, "r", encoding="utf-8") as f:
            report = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read {REPORT}: {exc}")

    if not isinstance(report, dict):
        fail("report must be a JSON object")

    extra = set(report) - ALLOWED_KEYS
    if extra:
        fail(f"unexpected keys: {sorted(extra)}")
    missing = ALLOWED_KEYS - set(report)
    if missing:
        fail(f"missing keys: {sorted(missing)}")

    if report["verdict"] != EXPECTED_VERDICT:
        fail(f"verdict = {report['verdict']!r}, expected {EXPECTED_VERDICT!r}")

    mitre = report["primary_mitre_technique"]
    if not isinstance(mitre, str) or not any(
        m in mitre.upper() for m in REQUIRED_MITRE
    ):
        fail(
            f"primary_mitre_technique = {mitre!r}, expected to contain one of "
            f"{sorted(REQUIRED_MITRE)!r}"
        )

    hosts = report["compromised_hosts"]
    if not isinstance(hosts, list) or not all(isinstance(h, str) for h in hosts):
        fail(f"compromised_hosts must be a list of strings: {hosts!r}")
    if {norm_host(h) for h in hosts} != REQUIRED_HOSTS:
        fail(f"compromised_hosts = {hosts!r}, expected exactly {sorted(REQUIRED_HOSTS)!r}")

    accounts = report["compromised_accounts"]
    if not isinstance(accounts, list) or not all(isinstance(a, str) for a in accounts):
        fail(f"compromised_accounts must be a list of strings: {accounts!r}")
    if {norm_account(a) for a in accounts} != REQUIRED_ACCOUNTS:
        fail(
            f"compromised_accounts = {accounts!r}, expected exactly "
            f"{sorted(REQUIRED_ACCOUNTS)!r}"
        )

    indicators = report["key_indicators"]
    if not isinstance(indicators, list) or not all(isinstance(i, str) for i in indicators):
        fail(f"key_indicators must be a list of strings: {indicators!r}")
    if len(indicators) < 2:
        fail(f"key_indicators needs at least 2 entries, got {len(indicators)}")

    values = evidence_strings()
    for ind in indicators:
        if not any(ind in v for v in values):
            fail(f"key_indicators entry {ind!r} not found verbatim in the evidence")

    blob = " ".join(indicators).lower()
    hits = {k for k in IOC_KEYWORDS if k in blob}
    if len(hits) < 2:
        fail(
            f"key_indicators must contain at least 2 distinct of {sorted(IOC_KEYWORDS)}; "
            f"found {sorted(hits)}"
        )

    print("PASS: report matches expected incident analysis")
    sys.exit(0)


if __name__ == "__main__":
    main()
