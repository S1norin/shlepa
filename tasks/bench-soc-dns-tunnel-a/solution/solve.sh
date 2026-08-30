#!/usr/bin/env bash
# Reference solution for bench-soc-dns-tunnel-a (SOCBench SCN-026).
# Documentation only — the dev engine never runs this file.
#
154 TXT queries, each a 28-char hex subdomain under cdn-284294b3.cloudsync-net.com with hex TXT answers — low-volume, high-entropy DNS tunneling C2 (T1071.004) from the WS-MKT-17 endpoint (owner e.taylor).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
