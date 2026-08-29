#!/usr/bin/env bash
# Reference solution for bench-soc-dll-hijack-a (SOCBench SCN-019).
# Documentation only — the dev engine never runs this file.
#
WS-IT-18, 09:04:09Z: Sysmon Image Loaded — unsigned winmm.dll (SHA256 FE5B44...) loaded next to C:\Program Files\SomeApp\app.exe. A legitimate Windows system DLL resolving from a writable application directory = DLL hijacking (T1574.001).
set -euo pipefail

cp /solution/expected_report.json /app/report.json
echo "Wrote /app/report.json"
