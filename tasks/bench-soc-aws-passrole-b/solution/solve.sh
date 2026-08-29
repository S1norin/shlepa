#!/usr/bin/env bash
# Reference solution for bench-soc-aws-passrole-b (SOCBench SCN-043).
# Documentation only — the dev engine never runs this file.
#
CloudTrail 2026-04-22: PassRole to AdminRole from external 91.108.4.22 (python-requests UA), then CreateFunction20150331 of util-dc83e7a3 bound to arn:aws:iam::123456789012:role/AdminRole — an IAM persistence/backdoor chain (T1098.003 / T1078.004) executed with the r.chen session from WS-ENG-04.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
