#!/usr/bin/env bash
set -uo pipefail

LOG_DIR=/logs/verifier
mkdir -p "$LOG_DIR"

if python3 /tests/report_grader.py >"$LOG_DIR/verifier.log" 2>&1; then
    echo 1 >"$LOG_DIR/reward.txt"
else
    echo 0 >"$LOG_DIR/reward.txt"
fi

cat "$LOG_DIR/verifier.log"
exit 0

