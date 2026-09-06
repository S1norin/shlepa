#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "verdict": "TRUE_POSITIVE_INCIDENT",
  "primary_mitre_technique": "T1114.002",
  "compromised_hosts": [],
  "compromised_accounts": ["cfo@contoso.com"],
  "key_indicators": ["DocuSign Pro Helper", "exfil@protonmail.com", "3847"]
}
JSON
