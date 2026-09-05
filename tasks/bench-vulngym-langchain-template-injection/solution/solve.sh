#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "vulnerability_found": true,
  "vulnerability_type": "CWE-1336 server-side template injection (SSTI)",
  "severity": "high",
  "entry_point": {"file": "libs/core/langchain_core/prompts/string.py", "line": 111},
  "critical_operation": {"file": "libs/core/langchain_core/utils/mustache.py", "line": 382},
  "data_flow": [
    {"file": "libs/core/langchain_core/prompts/string.py", "line": 111},
    {"file": "libs/core/langchain_core/prompts/string.py", "line": 121},
    {"file": "libs/core/langchain_core/utils/mustache.py", "line": 482},
    {"file": "libs/core/langchain_core/utils/mustache.py", "line": 371},
    {"file": "libs/core/langchain_core/utils/mustache.py", "line": 382}
  ],
  "root_cause": "The Mustache resolver splits attacker-controlled dotted names and falls back to unrestricted getattr access on arbitrary context objects.",
  "impact": "Applications accepting untrusted template structure can traverse Python object attributes and expose internal or sensitive state during rendering.",
  "recommendation": "Reject unsafe template identifiers and restrict traversal to explicitly supported primitive containers without arbitrary attribute access."
}
JSON

