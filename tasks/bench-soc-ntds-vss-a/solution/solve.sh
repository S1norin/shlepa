#!/usr/bin/env bash
# Reference solution for bench-soc-ntds-vss-a (SOCBench SCN-032).
# Documentation only — the dev engine never runs this file.
#
DC01, 09:02:03Z: k.brown runs `vssadmin create shadow /for=C:` (4688); at 09:04:25Z the same account reads \Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit (4663). Classic VSS-based NTDS.dit theft (T1003.003).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
