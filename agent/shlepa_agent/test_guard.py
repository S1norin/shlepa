"""w3-6: test-file hash guard (tamper invalidates results).

At bootstrap the harness records sha256 hashes of the in-environment
test files (``tests/`` tree, ``*.test.*`` files, root ``test.sh``).
Before accepting the run's own test results the files are re-hashed;
any change (content or deletion) marks the run's test results invalid
(``RunState.test_tampered``) and logs a ``test_tamper`` event.

Pure file reads only; never raises.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Safety caps so a hostile tree cannot make bootstrap hang/OOM.
MAX_FILES = 500
MAX_FILE_BYTES = 1_000_000


def _is_test_file(rel: Path) -> bool:
    """tests/ tree (top-level), *.test.* anywhere, or a test.sh file."""
    if rel.parts and rel.parts[0] == "tests":
        return True
    name = rel.name
    return name == "test.sh" or ".test." in name


def bootstrap_test_hashes(workdir: Path) -> dict[str, str]:
    """Hash every in-environment test file; returns {relpath: sha256}."""
    hashes: dict[str, str] = {}
    for p in sorted(workdir.rglob("*")):
        if len(hashes) >= MAX_FILES:
            break
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(workdir)
        except ValueError:
            continue
        if not _is_test_file(rel):
            continue
        try:
            if p.stat().st_size > MAX_FILE_BYTES:
                continue
            hashes[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return hashes


def check_test_hashes(workdir: Path, hashes: dict[str, str]) -> list[str]:
    """Re-hash the recorded files; return the relpaths that changed or
    are missing (empty list = unchanged)."""
    changed: list[str] = []
    for rel in sorted(hashes):
        p = workdir / rel
        try:
            if hashlib.sha256(p.read_bytes()).hexdigest() != hashes[rel]:
                changed.append(rel)
        except OSError:
            changed.append(rel)
    return changed
