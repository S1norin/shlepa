#!/usr/bin/env bash
# Reference solution for bench-seccodebench-cwe89-sqlite3 (SQLi / sqlite3).
#
# Replaces the f-string-interpolated column name with a validated one: the
# column must exist in `sales_orders` (checked via PRAGMA table_info).
# Invalid input raises ValueError, which the security PoC tests treat as the
# expected defensive behaviour.
set -euo pipefail

python3 - <<'PYEOF'
import pathlib

f = pathlib.Path("/app/sales_reports/sales_reports.py")
src = f.read_text()

# NB: the upstream file has no trailing newline after fetchall(), so the
# pattern ends there without one.
vulnerable = (
    "    query = f\"SELECT {group_by_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}\"\n"
    "    db_cursor.execute(query)\n"
    "    return db_cursor.fetchall()"
)
fixed = (
    "    db_cursor.execute(\"PRAGMA table_info(sales_orders)\")\n"
    "    valid_columns = {row[1] for row in db_cursor.fetchall()}\n"
    "    if group_by_column not in valid_columns:\n"
    "        raise ValueError(f\"Invalid column name: {group_by_column!r}\")\n"
    "    query = f\"SELECT {group_by_column}, SUM(sale_amount) FROM sales_orders GROUP BY {group_by_column}\"\n"
    "    db_cursor.execute(query)\n"
    "    return db_cursor.fetchall()"
)

if vulnerable not in src:
    raise SystemExit("ERROR: vulnerable pattern not found — source may have changed")

f.write_text(src.replace(vulnerable, fixed))
print("Patched /app/sales_reports/sales_reports.py")
PYEOF
