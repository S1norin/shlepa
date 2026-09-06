#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier
python3 /tests/report_grader.py >/logs/verifier/verifier.log 2>&1
if [[ $? -eq 0 && -f /app/report.json ]]; then echo 1 >/logs/verifier/reward.txt; else echo 0 >/logs/verifier/reward.txt; fi
exit 0
