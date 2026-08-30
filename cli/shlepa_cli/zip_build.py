"""Build the submission zip from agent/ (flat layout, telemetry excluded).

The zip is what gets handed to the contest runtime: run.sh at the root
(executable bit preserved via zip attrs), agent.py, the flat tools/ scripts,
and the shlepa_agent package. Development-only artifacts (telemetry module,
pyproject, lockfile, tests, caches) are excluded so the submission cannot
ship telemetry.
"""

import os
import subprocess
import zipfile
from pathlib import Path

#: Hard cap for the submission archive.
MAX_ZIP_BYTES = 10 * 1024 * 1024

#: Package directory copied into the zip root.
PACKAGE_DIR = "shlepa_agent"

#: Flat agent-facing scripts directory copied into the zip root
#: (run as `python3 tools/<name>.py` from the /app cwd).
TOOLS_DIR = "tools"

#: Directory names excluded anywhere inside the package.
EXCLUDED_DIR_NAMES = {"telemetry", "__pycache__"}

#: File extensions excluded anywhere.
EXCLUDED_SUFFIXES = (".pyc", ".pyo")

#: File names excluded anywhere (agent-root build artifacts never ship).
EXCLUDED_FILE_NAMES = {"pyproject.toml", "uv.lock"}

EXEC_MODE = 0o755


class ZipBuildError(RuntimeError):
    """Raised when the submission cannot be built or fails checks."""


def _git_short_sha(repo_root: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _is_excluded(rel: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if rel.suffix in EXCLUDED_SUFFIXES:
        return True
    if rel.name in EXCLUDED_FILE_NAMES:
        return True
    return False


def build_submission_zip(repo_root: Path) -> Path:
    """Build dist/submission-<sha>.zip from repo_root/agent.

    Raises ZipBuildError if agent/run.sh is missing or not executable,
    or if the resulting archive exceeds MAX_ZIP_BYTES (10MB).
    """
    agent_dir = repo_root / "agent"
    if not agent_dir.is_dir():
        raise ZipBuildError(f"agent directory not found: {agent_dir}")

    run_sh = agent_dir / "run.sh"
    if not run_sh.is_file():
        raise ZipBuildError("agent/run.sh is missing")
    if not os.access(run_sh, os.X_OK):
        raise ZipBuildError("agent/run.sh is not executable")
    agent_py = agent_dir / "agent.py"
    if not agent_py.is_file():
        raise ZipBuildError("agent/agent.py is missing")
    pkg_dir = agent_dir / PACKAGE_DIR
    if not pkg_dir.is_dir():
        raise ZipBuildError(f"agent/{PACKAGE_DIR}/ is missing")

    sha = _git_short_sha(repo_root)
    dist_dir = repo_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    out = dist_dir / f"submission-{sha or 'dev'}.zip"

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        # run.sh at the zip root with the executable bit preserved.
        info = zipfile.ZipInfo("run.sh")
        info.external_attr = (EXEC_MODE << 16) | 0x8000  # regular file
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, run_sh.read_bytes())
        zf.write(agent_py, "agent.py")
        tools_dir = agent_dir / TOOLS_DIR
        if tools_dir.is_dir():
            for path in sorted(tools_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(agent_dir)
                if _is_excluded(rel):
                    continue
                zf.write(path, rel.as_posix())
        for path in sorted(pkg_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(agent_dir)
            if _is_excluded(rel):
                continue
            zf.write(path, rel.as_posix())

    size = out.stat().st_size
    if size > MAX_ZIP_BYTES:
        out.unlink(missing_ok=True)
        raise ZipBuildError(
            f"submission zip is {size} bytes, exceeds the 10MB limit; "
            "remove large files from agent/"
        )
    return out


__all__ = [
    "MAX_ZIP_BYTES",
    "ZipBuildError",
    "build_submission_zip",
    "EXEC_MODE",
]
