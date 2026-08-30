#!/usr/bin/env bash
# Reference solution for bench-soc-dll-hijack-b (SOCBench SCN-039).
# Documentation only — the dev engine never runs this file.
#
WS-MKT-11, 09:04:12Z: Sysmon Image Loaded — unsigned dwmapi.dll (SHA256 1C1D3B...) loaded next to C:\Program Files\SomeApp\app.exe. A legitimate Windows system DLL resolving from a writable application directory = DLL hijacking (T1574.001).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
