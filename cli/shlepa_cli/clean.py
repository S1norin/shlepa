"""tmp/ workspace cleanup for 'shlepa clean'.

Run workspaces live in tmp/<timestamp>-<slug>/; this removes entries
older than the cutoff, always keeping tmp/README.md.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

DEFAULT_MAX_AGE_DAYS = 7


def clean(
    tmp_dir: Path,
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    now: float | None = None,
) -> list[Path]:
    """Remove tmp/ entries older than ``max_age_days``; return removed paths.

    ``now`` is injectable for tests (time.time() by default). A missing
    tmp/ directory is not an error.
    """
    tmp_dir = Path(tmp_dir)
    if not tmp_dir.is_dir():
        return []
    now = time.time() if now is None else now
    max_age = max_age_days * 86400
    removed: list[Path] = []
    for entry in sorted(tmp_dir.iterdir()):
        if entry.name == "README.md":
            continue
        if now - entry.stat().st_mtime <= max_age:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        removed.append(entry)
    return removed
