#!/usr/bin/env python3
"""Deterministic attack-surface recon for the shlepa agent.

Zero dependencies (Python stdlib only), stateless, no LLM. This tool maps a
surface; it never claims a vulnerability.

Modes:
  python3 tools/recon.py <url>           network map of a live web target
  python3 tools/recon.py --code <dir>    code-surface map of a source tree
  python3 tools/recon.py --data <dir>    data/log-surface map of an evidence dir

Contract:
  - compact flat JSON on stdout, hard total cap 8192 bytes (per-field caps,
    progressive list truncation as a backstop)
  - deterministic: fixed probe lists and order; only stats.elapsed_s varies
  - fail-safe: a stage failure emits its section with an error note and never
    aborts the run; exit code 0 on any completed mode
  - internal wall budget ~100s so the run fits the bash tool's 120s cap

This script is a thin CLI wrapper; the engine lives in
``shlepa_agent.recon`` (also importable by the agent's recon tool).
"""

from __future__ import annotations

import sys
from pathlib import Path

# The engine lives in the shlepa_agent package at the agent root. The agent
# sets PYTHONPATH for us, but keep the script usable when run directly
# (python3 tools/recon.py) from any cwd without it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from shlepa_agent.recon import (  # noqa: E402
    err_note,
    recon_code,
    recon_data,
    recon_web,
    render,
)


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    try:
        if argv[0] == "--code":
            out = recon_code(Path(argv[1]).resolve())
        elif argv[0] == "--data":
            out = recon_data(Path(argv[1]).resolve())
        else:
            out = recon_web(argv[0])
    except Exception as e:
        out = {"error": err_note(e)}
    print(render(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
