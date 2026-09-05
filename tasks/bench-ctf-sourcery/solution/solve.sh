#!/usr/bin/env bash
set -euo pipefail
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
unzip -q /app/sourcery.zip
commit=$(git fsck --full --no-reflogs --unreachable 2>/dev/null | awk '/unreachable commit/{print $3; exit}')
git show "${commit}^:__pycache__/secret.cpython-38.pyc" > secret.pyc
/app/.venv/bin/pydisasm secret.pyc > disassembly.txt
python3 - <<'PY'
import ast, base64, re
text = open("disassembly.txt").read()
pairs = []
for raw in re.findall(r"#\s+\d+: (\(\d+, '[^']'\))", text):
    pairs.append(ast.literal_eval(raw))
encoded = "".join(ch for _, ch in sorted(pairs))
flag = base64.b64decode(encoded).decode()
open("/app/flag.txt", "w").write(flag + "\n")
PY
