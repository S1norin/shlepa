#!/usr/bin/env bash
set -euo pipefail
cat > /app/security_report.json <<'JSON'
{
  "findings": [
    {
      "title": "Export filename escapes the designated directory",
      "severity": "high",
      "category": "CWE-22: Improper Limitation of a Pathname to a Restricted Directory",
      "location": "src/ExportCli.java, saveExport, Files.write(destination, contents)",
      "evidence": "EXPORT_ROOT.resolve(requestedName) does not confine the result. A name such as ../../tmp/overwritten.csv passes the suffix check and Files.write stores data outside /app/exports.",
      "impact": "An attacker can create or overwrite CSV-named files in locations writable by the process.",
      "recommendation": "Reject absolute paths, normalize the resolved path and require it to start with the normalized export root; use real/canonical paths and no-follow semantics to prevent symbolic link escapes before writing."
    }
  ]
}
JSON
