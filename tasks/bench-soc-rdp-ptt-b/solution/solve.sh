#!/usr/bin/env bash
# Reference solution for bench-soc-rdp-ptt-b (SOCBench SCN-036).
# Documentation only — the dev engine never runs this file.
#
DB-SRV-01, 09:05:20Z: LogonType 10 (RemoteInteractive) Kerberos logon for r.chen, workstation WS-HR-10 (10.10.3.236). Zeek shows the matching long 3389 session (10.10.9.150 -> 10.10.5.41, ~2517 s). RDP lateral movement with pass-the-ticket (T1021.001 / T1550.003).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
