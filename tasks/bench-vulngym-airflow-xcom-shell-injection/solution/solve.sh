#!/usr/bin/env bash
set -euo pipefail
cat > /app/report.json <<'JSON'
{
  "vulnerability_found": true,
  "vulnerability_type": "CWE-78 shell command injection",
  "severity": "high",
  "entry_point": {"file": "airflow-core/src/airflow/example_dags/example_xcom.py", "line": 83},
  "critical_operation": {"file": "airflow-core/src/airflow/example_dags/example_xcom.py", "line": "80-87"},
  "data_flow": [
    {"file": "airflow-core/src/airflow/example_dags/example_xcom.py", "line": 83},
    {"file": "airflow-core/src/airflow/example_dags/example_xcom.py", "line": 84},
    {"file": "airflow-core/src/airflow/example_dags/example_xcom.py", "line": "80-87"}
  ],
  "root_cause": "Untrusted XCom values are interpolated directly into a BashOperator command without shell-safe quoting or separation of data from code.",
  "impact": "A user able to influence the referenced XCom values can inject shell syntax and execute commands with the Airflow worker process privileges.",
  "recommendation": "Do not embed XCom values in bash_command strings; pass them through environment variables or arguments and apply context-appropriate quoting."
}
JSON

