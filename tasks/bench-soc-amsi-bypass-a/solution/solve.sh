#!/usr/bin/env bash
# Reference solution for bench-soc-amsi-bypass-a (SOCBench SCN-022).
# Documentation only — the dev engine never runs this file.
#
WS-HR-20, 09:01:17Z: event 4104 script block sets AmsiUtils.amsiInitFailed=true — the classic AMSI-bypass one-liner (T1562.001). Thirty-three seconds later Sysmon shows powershell.exe opening C:\Windows\System32\amsi.dll with write access (0x1410).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
