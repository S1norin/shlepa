#!/usr/bin/env bash
# Reference solution for bench-soc-proc-hollow-b (SOCBench SCN-041).
# Documentation only — the dev engine never runs this file.
#
WS-MKT-03, 09:02:12Z: Sysmon CreateRemoteThread — C:\Users\t.nguyen\AppData\Roaming\svchost.exe injected into C:\Windows\System32\svchost.exe via LoadLibraryA. Process hollowing (T1055.012), here carrying a Cobalt Strike beacon.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
