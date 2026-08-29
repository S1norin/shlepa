#!/usr/bin/env bash
# Reference solution for bench-soc-amsi-bypass-b (SOCBench SCN-042).
# Documentation only — the dev engine never runs this file.
#
WS-FIN-02, 09:01:00Z: event 4104 script block sets AmsiUtils.amsiInitFailed=true — the AMSI-bypass one-liner (T1562.001). Sysmon then shows powershell.exe opening amsi.dll with write access (0x1410) at 09:01:47Z.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
