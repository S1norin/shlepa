#!/usr/bin/env bash
# Reference solution for bench-soc-rdp-ptt-a (SOCBench SCN-016).
# Documentation only — the dev engine never runs this file.
#
FS-FINANCE-02, 09:05:14Z: LogonType 10 (RemoteInteractive) Kerberos logon for k.brown, workstation WS-IT-07 (10.10.7.100). Zeek shows the matching long 3389 session (10.10.2.50 -> 10.10.4.124, ~713 s). RDP lateral movement with pass-the-ticket (T1021.001 / T1550.003); the other logons in the window are benign context.
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
