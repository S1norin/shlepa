#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "vulnerability_found": true,
  "vulnerability_type": "CWE-362 race condition causing a cross-client data leak",
  "severity": "high",
  "entry_point": {"file": "src/server/webStandardStreamableHttp.ts", "line": 321},
  "critical_operation": {"file": "src/server/webStandardStreamableHttp.ts", "line": 938},
  "data_flow": [
    {"file": "src/server/webStandardStreamableHttp.ts", "line": 321},
    {"file": "src/server/webStandardStreamableHttp.ts", "line": 678},
    {"file": "src/server/webStandardStreamableHttp.ts", "line": 700},
    {"file": "src/server/webStandardStreamableHttp.ts", "line": 751},
    {"file": "src/server/webStandardStreamableHttp.ts", "line": 938}
  ],
  "root_cause": "A reusable transport stores request-ID to stream mappings in shared instance state, so equal JSON-RPC IDs from concurrent clients overwrite each other.",
  "impact": "Concurrent clients can cause a private JSON-RPC response to be routed to another client's HTTP stream, violating tenant and request isolation.",
  "recommendation": "Scope mappings by client or request context, reject unsafe transport reuse, and remove mappings atomically when each response completes."
}
JSON

