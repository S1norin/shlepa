#!/usr/bin/env bash
# Reference solution for bench-soc-scanner-fp (SOCBench SCN-029).
# Documentation only — the dev engine never runs this file.
#
# The flagged burst is a port sweep from the dedicated pentest segment
# (10.10.200.0/24) entirely inside the approved engagement window
# (2026-04-20 09:00-10:00 UTC per CM-2026-0417), so the correct verdict is
# FALSE_POSITIVE_AUTHORIZED_PENTEST.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
