#!/usr/bin/env bash
set -euo pipefail
cat > /app/security_report.json <<'JSON'
{
  "findings": [
    {
      "title": "Reflected cross-site scripting in note preview",
      "severity": "high",
      "category": "CWE-79: Improper Neutralization of Input During Web Page Generation",
      "location": "src/app.py, preview_note, GET /preview",
      "evidence": "The note query-string value is interpolated directly into an HTML f-string. A note such as <script>alert(1)</script> becomes executable response markup.",
      "impact": "An attacker can make a victim's browser execute attacker-controlled script in the application's origin.",
      "recommendation": "HTML-escape note with html.escape before interpolation, or render it through an auto-escaping template engine."
    }
  ]
}
JSON
