#!/usr/bin/env bash
# Reference solution for bench-soc-https-beacon-b (SOCBench SCN-047).
# Documentation only — the dev engine never runs this file.
#
26 fixed-interval HTTPS connections (small, symmetric transfers, ~5 min cadence) from internal endpoints to external 198.51.100.47:443 — a Cobalt Strike HTTPS beacon (T1071.001) on the WS-ENG-09 endpoint (owner m.jones).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
