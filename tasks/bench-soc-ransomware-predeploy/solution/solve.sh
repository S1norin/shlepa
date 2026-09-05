#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "verdict": "TRUE_POSITIVE_INCIDENT",
  "primary_mitre_technique": "T1490",
  "compromised_hosts": ["WS-ACCT-05"],
  "compromised_accounts": ["j.doe@corp.local"],
  "key_indicators": [
    "vssadmin delete shadows /all /quiet",
    "C:\\Windows\\Temp\\syscheck.exe",
    "schtasks /create /tn \"SystemHealthCheck\" /tr \"C:\\Windows\\Temp\\syscheck.exe\" /sc ONSTART /ru SYSTEM /f"
  ]
}
JSON
