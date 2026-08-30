#!/usr/bin/env bash
# Reference solution for bench-soc-proc-hollow-a (SOCBench SCN-021).
# Documentation only — the dev engine never runs this file.
#
WS-MKT-10, 09:02:15Z: Sysmon CreateRemoteThread — C:\Users\t.nguyen\AppData\Roaming\svchost.exe injected into C:\Windows\System32\svchost.exe via LoadLibraryA. A user-writable svchost.exe planting into the signed service = process hollowing (T1055.012), here carrying a Cobalt Strike beacon.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
