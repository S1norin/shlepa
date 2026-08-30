#!/usr/bin/env bash
# Reference solution for bench-soc-aws-passrole-a (SOCBench SCN-023).
# Documentation only — the dev engine never runs this file.
#
CloudTrail 2026-04-26: PassRole to AdminRole from external 45.33.32.156 (python-requests UA), then CreateFunction20150331 of util-8afc2c04 bound to arn:aws:iam::123456789012:role/AdminRole — an IAM persistence/backdoor chain (T1098.003 / T1078.004) executed with the s.garcia session from WS-FIN-10.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
