"""Deterministic checks for the public competition submission contract.

This module validates only requirements that can be established from the
artifact.  ``submit-test`` supplies the complementary Harbor/ACP runtime
validation; closed evaluation tasks and their limits cannot be validated
locally.
"""

from __future__ import annotations

import ast
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from shlepa_cli.zip_build import MAX_ZIP_BYTES


FORBIDDEN_PATH_PARTS = {"telemetry", "tests", "__pycache__"}
FORBIDDEN_PATH_NAMES = {"pyproject.toml", "uv.lock", "requirements.txt"}
FORBIDDEN_IMPORT_ROOTS = {"opentelemetry", "openinference", "mlflow"}
RUNTIME_INSTALL_RE = re.compile(r"\b(?:pip|uv|apt(?:-get)?)\s+(?:install|add)\b")
REQUIRED_ENV_VARS = {"LOCAL_AGENT_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY"}


@dataclass(frozen=True)
class ComplianceCheck:
    """One public-contract assertion and its result."""

    name: str
    ok: bool
    detail: str


def _forbidden_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots = {node.module.split(".")[0]}
        else:
            continue
        found.update(roots & FORBIDDEN_IMPORT_ROOTS)
    return found


def check_submission(zip_path) -> list[ComplianceCheck]:
    """Validate the built archive against locally testable public rules."""
    path = zip_path
    checks: list[ComplianceCheck] = []
    if not path.is_file():
        return [ComplianceCheck("archive", False, f"submission zip not found: {path}")]

    size = path.stat().st_size
    checks.append(
        ComplianceCheck(
            "archive_size",
            size <= MAX_ZIP_BYTES,
            f"{size} bytes (local cap {MAX_ZIP_BYTES} bytes)",
        )
    )
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            names = [info.filename for info in infos]
            invalid = [
                name
                for name in names
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts
            ]
            checks.append(
                ComplianceCheck(
                    "safe_paths",
                    not invalid,
                    "no unsafe paths" if not invalid else ", ".join(invalid),
                )
            )
            run_sh = next((info for info in infos if info.filename == "run.sh"), None)
            checks.append(
                ComplianceCheck(
                    "entrypoint",
                    run_sh is not None,
                    "run.sh at archive root" if run_sh else "run.sh missing from archive root",
                )
            )
            if run_sh is not None:
                mode = (run_sh.external_attr >> 16) & 0o777
                checks.append(
                    ComplianceCheck(
                        "entrypoint_mode",
                        bool(mode & 0o111),
                        f"run.sh mode {mode:03o}",
                    )
                )
                script = zf.read(run_sh).decode("utf-8", errors="replace")
                forbidden_commands = RUNTIME_INSTALL_RE.findall(script)
                checks.append(
                    ComplianceCheck(
                        "no_runtime_installs",
                        not forbidden_commands,
                        "no package-install command in run.sh"
                        if not forbidden_commands
                        else f"found: {', '.join(forbidden_commands)}",
                    )
                )
            forbidden_paths = [
                name
                for name in names
                if set(PurePosixPath(name).parts) & FORBIDDEN_PATH_PARTS
                or PurePosixPath(name).name in FORBIDDEN_PATH_NAMES
            ]
            checks.append(
                ComplianceCheck(
                    "development_files_excluded",
                    not forbidden_paths,
                    "no telemetry, tests, caches, or dependency metadata"
                    if not forbidden_paths
                    else ", ".join(forbidden_paths),
                )
            )

            forbidden_imports: dict[str, set[str]] = {}
            shipped_source: list[str] = [script] if run_sh is not None else []
            for name in names:
                if name.endswith(".py"):
                    source = zf.read(name).decode("utf-8", errors="strict")
                    shipped_source.append(source)
                    found = _forbidden_imports(source)
                    if found:
                        forbidden_imports[name] = found
            checks.append(
                ComplianceCheck(
                    "no_dev_dependencies",
                    not forbidden_imports,
                    "no telemetry or MLflow imports"
                    if not forbidden_imports
                    else "; ".join(
                        f"{name}: {', '.join(sorted(roots))}"
                        for name, roots in forbidden_imports.items()
                    ),
                )
            )
            all_source = "\n".join(shipped_source)
            missing_vars = sorted(name for name in REQUIRED_ENV_VARS if name not in all_source)
            checks.append(
                ComplianceCheck(
                    "endpoint_contract",
                    not missing_vars,
                    "the artifact reads the supplied model and endpoint variables"
                    if not missing_vars
                    else f"artifact does not reference: {', '.join(missing_vars)}",
                )
            )
    except (OSError, UnicodeDecodeError, zipfile.BadZipFile, SyntaxError) as exc:
        checks.append(ComplianceCheck("archive_readable", False, str(exc)))
    return checks


def passed(checks: list[ComplianceCheck]) -> bool:
    """Return whether every deterministic compliance check passed."""
    return bool(checks) and all(check.ok for check in checks)
