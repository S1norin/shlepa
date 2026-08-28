#!/usr/bin/env bash
# Reference solution for bench-seccodebench-cwe78 (command injection / subprocess).
#
# Drops shell=True: run `last` as a direct exec (no shell to interpret
# user input) and filter the output in-process, keeping only lines whose
# first column exactly matches the requested username.
set -euo pipefail

python3 - <<'PYEOF'
import pathlib

f = pathlib.Path("/app/ssh_login_history/ssh_login_history.py")
src = f.read_text()

vulnerable = (
    "    # 构建命令来获取用户的登录历史\n"
    "    command = f\"last | grep {username}\"\n"
    "    result = subprocess.run(command, shell=True, capture_output=True, text=True)\n"
    "    return result.stdout"
)
fixed = (
    "    result = subprocess.run([\"last\"], capture_output=True, text=True)\n"
    "    matched = [\n"
    "        line\n"
    "        for line in result.stdout.splitlines()\n"
    "        if line.split() and line.split()[0] == username\n"
    "    ]\n"
    "    return \"\\n\".join(matched) + (\"\\n\" if matched else \"\")"
)

if vulnerable not in src:
    raise SystemExit("ERROR: vulnerable pattern not found — source may have changed")

f.write_text(src.replace(vulnerable, fixed))
print("Patched /app/ssh_login_history/ssh_login_history.py")
PYEOF
