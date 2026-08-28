#!/usr/bin/env bash
# Reference solution for bench-soc-ntds-vss (SOCBench SCN-012).
# Documentation only — the dev engine never runs this file.
#
# DC01, 09:02:15Z: j.doe runs `vssadmin create shadow /for=C:` (event 4688).
# Two minutes later (09:04:28Z, event 4663) the same account reads
# \Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit with access
# granted — the classic VSS-based NTDS.dit theft (T1003.003). The benign
# logons (incl. j.doe on WS-MKT-09 at 09:01:22Z) are context, not the
# malicious activity: the malicious events execute on DC01.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
