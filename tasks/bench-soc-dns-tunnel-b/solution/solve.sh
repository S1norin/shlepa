#!/usr/bin/env bash
# Reference solution for bench-soc-dns-tunnel-b (SOCBench SCN-046).
# Documentation only — the dev engine never runs this file.
#
81 TXT queries, each a 28-char hex subdomain under cdn-b3c16c14.cloudsync-net.com with hex TXT answers — DNS tunneling C2 (T1071.004) from the WS-IT-11 endpoint (owner s.garcia).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
