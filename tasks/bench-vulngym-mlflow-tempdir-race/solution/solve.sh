#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "vulnerability_found": true,
  "vulnerability_type": "CWE-377 unsafe temporary directory permissions and race condition",
  "severity": "high",
  "entry_point": {"file": "mlflow/pyfunc/__init__.py", "line": 2049},
  "critical_operation": {"file": "mlflow/utils/file_utils.py", "line": 761},
  "data_flow": [
    {"file": "mlflow/pyfunc/__init__.py", "line": 2049},
    {"file": "mlflow/pyfunc/__init__.py", "line": 2334},
    {"file": "mlflow/utils/file_utils.py", "line": 758},
    {"file": "mlflow/utils/file_utils.py", "line": 761}
  ],
  "root_cause": "A safely created private temporary directory is immediately changed to mode 0777 before model artifacts and executable content are written into it.",
  "impact": "A local unprivileged user can race the artifact download and replace or inject files that are later loaded under the victim MLflow process privileges.",
  "recommendation": "Keep the directory owner-only, avoid shared writable locations, and use atomic creation and file operations that reject links and replacements."
}
JSON

