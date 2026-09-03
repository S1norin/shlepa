#!/usr/bin/env python3
"""Regenerate the recon CLI golden outputs for the parity tests.

Usage (from anywhere; paths are computed relative to this file):

    python3 tests/fixtures/recon/gen_goldens.py

Generates, next to this file:
  - code.golden.json: full CLI stdout of ``recon.py --code code_fixture``
  - data.golden.json: full CLI stdout of ``recon.py --data data_fixture``
  - web.golden.json : CLI stdout of ``recon.py http://127.0.0.1:18473/``
    against the fixture web server (the same handler the test suite uses),
    with the volatile sections ``stats`` and ``ports_open`` removed
    (ports_open depends on what else listens on the host's 127.0.0.1;
    elapsed_s varies by definition).

Run this BEFORE any deliberate behavior change to recon (e.g. the web
deadline fix) so the parity tests in tests/test_recon.py can assert the
new CLI output against the recorded baseline.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parents[2]
RECON = AGENT_ROOT / "tools" / "recon.py"
WEB_PORT = 18473


def _run_cli(*args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(RECON), *args],
        capture_output=True, text=True, timeout=180, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"recon CLI failed ({args}): {proc.stderr}")
    return proc.stdout


def gen_code_data() -> None:
    for mode, fixture, golden in (
        ("--code", "code_fixture", "code.golden.json"),
        ("--data", "data_fixture", "data.golden.json"),
    ):
        out = _run_cli(mode, str(HERE / fixture))
        json.loads(out)  # must be valid JSON
        (HERE / golden).write_text(out)
        print(f"wrote {golden} ({len(out)} bytes)")


def gen_web() -> None:
    # share the fixture server handler with the test suite
    sys.path.insert(0, str(AGENT_ROOT / "tests"))
    import test_recon as t

    server, port = t._start_web_server(port=WEB_PORT)
    try:
        out = _run_cli(f"http://127.0.0.1:{port}/")
        data = json.loads(out)
        for volatile in ("stats", "ports_open"):
            data.pop(volatile, None)
        text = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
        (HERE / "web.golden.json").write_text(text)
        print(f"wrote web.golden.json ({len(text)} bytes)")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    gen_code_data()
    gen_web()
