#!/usr/bin/env bash
set -euo pipefail
cat > /app/security_report.json <<'JSON'
{
  "findings": [
    {
      "title": "Server-side request forgery in link-card fetcher",
      "severity": "high",
      "category": "CWE-918: Server-Side Request Forgery",
      "location": "src/main.go, fetchCard, http.Get(rawURL)",
      "evidence": "The only validation is a case-sensitive https:// prefix check before http.Get. An attacker can supply https://127.0.0.1/, a private or link-local destination, or a public URL that redirects to one.",
      "impact": "The service can be induced to read internal HTTPS services or cloud metadata-like endpoints from its trusted network position.",
      "recommendation": "Parse URLs strictly, resolve every hostname, reject loopback/private/link-local IP addresses, restrict ports, and repeat the same validation for every redirect using a custom client and dialer."
    }
  ]
}
JSON
