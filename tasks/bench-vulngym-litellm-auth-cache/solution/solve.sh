#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "vulnerability_found": true,
  "vulnerability_type": "CWE-287 authentication bypass through cache key collision",
  "severity": "critical",
  "entry_point": {"file": "litellm/proxy/auth/user_api_key_auth.py", "line": 1209},
  "critical_operation": {"file": "litellm/proxy/auth/handle_jwt.py", "line": 506},
  "data_flow": [
    {"file": "litellm/proxy/auth/user_api_key_auth.py", "line": 1236},
    {"file": "litellm/proxy/auth/user_api_key_auth.py", "line": 500},
    {"file": "litellm/proxy/auth/handle_jwt.py", "line": 1146},
    {"file": "litellm/proxy/auth/handle_jwt.py", "line": 506}
  ],
  "root_cause": "OIDC user information is cached under only the first twenty token characters, which are commonly identical across distinct signed JWTs.",
  "impact": "An attacker can collide with another token's cache entry and receive the cached identity, bypassing authentication and impersonating that user.",
  "recommendation": "Key the cache with a collision-resistant digest of the complete token and retain normal signature, issuer, audience, and expiry validation."
}
JSON

