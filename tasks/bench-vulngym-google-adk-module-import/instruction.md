# Source audit

The `/app` directory contains a curated, vulnerable source snapshot from a real open-source project. Perform a white-box security review and identify the single intended vulnerability. Do not modify the supplied source files and do not exploit any external system.

Write `/app/report.json` as one JSON object with exactly these keys:

```json
{
  "vulnerability_found": true,
  "vulnerability_type": "specific vulnerability class or CWE",
  "severity": "low|medium|high|critical",
  "entry_point": {"file": "path relative to /app", "line": 1},
  "critical_operation": {"file": "path relative to /app", "line": "1-2"},
  "data_flow": [
    {"file": "path relative to /app", "line": 1},
    {"file": "path relative to /app", "line": 2}
  ],
  "root_cause": "technical explanation",
  "impact": "security impact and required attacker conditions",
  "recommendation": "concrete remediation"
}
```

`line` may be a positive integer or an inclusive `start-end` string. Trace the actual control/data path in the supplied snapshot; a generic vulnerability guess is not sufficient.

