#!/usr/bin/env bash
# Reference solution for bench-seccodebench-cwe89 (SQLi / psycopg2).
#
# Replaces the f-string-interpolated query with a parameterized one.
# The call goes through the module-level `get_database_cursor` name (the
# functional test patches that symbol) and the row-to-dict conversion is
# preserved.
set -euo pipefail

python3 - <<'PYEOF'
import pathlib

f = pathlib.Path("/app/user_activity_logger/user_activity_logger.py")
src = f.read_text()

vulnerable = (
    "    query = f\"SELECT * FROM user_logs WHERE username = '{username}'\"\n"
    "    cursor.execute(query)\n"
)
fixed = (
    "    cursor.execute(\"SELECT * FROM user_logs WHERE username = %s\", (username,))\n"
)

if vulnerable not in src:
    raise SystemExit("ERROR: vulnerable pattern not found — source may have changed")

f.write_text(src.replace(vulnerable, fixed))
print("Patched /app/user_activity_logger/user_activity_logger.py")
PYEOF
