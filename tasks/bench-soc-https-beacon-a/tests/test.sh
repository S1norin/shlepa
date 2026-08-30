#!/usr/bin/env bash
# Verifier for bench-soc-https-beacon-a (SOCBench SCN-027, adapted).
#
# The agent's /app/report.json is graded field-by-field by
# report_grader.py (verdict taxonomy per SOCBench, plus MITRE technique,
# host/account attribution, and evidence-verbatim IOC checks). Reward 1
# iff all expected fields match.
set -uo pipefail

LOG_DIR="/logs/verifier"
REWARD="$LOG_DIR/reward.txt"
mkdir -p "$LOG_DIR"

PYTHON="python3"
if [[ ! -x "$(command -v python3 || true)" ]]; then
    PYTHON="/app/.venv/bin/python"
fi

out="$("$PYTHON" /tests/report_grader.py 2>&1)"
rc=$?
printf '%s\n' "$out" >> "$LOG_DIR/verifier.log"
echo "$out"

if [[ $rc -eq 0 && -f /app/report.json ]]; then
    echo 1 > "$REWARD"
else
    echo 0 > "$REWARD"
fi
exit 0
