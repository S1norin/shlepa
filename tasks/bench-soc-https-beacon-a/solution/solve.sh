#!/usr/bin/env bash
# Reference solution for bench-soc-https-beacon-a (SOCBench SCN-027).
# Documentation only — the dev engine never runs this file.
#
17 fixed-interval HTTPS connections (small, symmetric transfers, ~5 min cadence) from internal endpoints to external 198.51.100.47:443 — a Cobalt Strike HTTPS beacon (T1071.001) on the WS-HR-04 endpoint (owner p.adams).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
