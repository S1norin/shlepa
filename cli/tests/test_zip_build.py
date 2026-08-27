"""Tests for the submission zip builder (shlepa zip)."""

import ast
import os
import stat
import zipfile
from pathlib import Path

import pytest

from shlepa_cli.zip_build import ZipBuildError, build_submission_zip


def _make_agent_tree(agent_dir: Path) -> None:
    (agent_dir / "shlepa_agent").mkdir(parents=True)
    (agent_dir / "shlepa_agent" / "telemetry").mkdir()
    (agent_dir / "shlepa_agent" / "__pycache__").mkdir()
    (agent_dir / "run.sh").write_text("#!/bin/bash\nexec python3 -m shlepa_agent \"$1\"\n")
    os.chmod(agent_dir / "run.sh", 0o755)
    (agent_dir / "agent.py").write_text("print('agent entry')\n")
    (agent_dir / "shlepa_agent" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (agent_dir / "shlepa_agent" / "core.py").write_text("X = 1\n")
    (agent_dir / "shlepa_agent" / "telemetry" / "__init__.py").write_text("T = 1\n")
    (agent_dir / "shlepa_agent" / "__pycache__" / "core.cpython-312.pyc").write_bytes(b"\x00")
    (agent_dir / "pyproject.toml").write_text("[project]\n")
    (agent_dir / "uv.lock").write_text("")


def test_build_zip_entries_and_exclusions(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    out = build_submission_zip(tmp_path)

    assert out.exists()
    assert out.parent == tmp_path / "dist"
    assert out.name == "submission-dev.zip"  # not a git checkout
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
    assert names == {
        "run.sh",
        "agent.py",
        "shlepa_agent/__init__.py",
        "shlepa_agent/core.py",
    }


def test_run_sh_kept_executable_in_zip(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    out = build_submission_zip(tmp_path)
    with zipfile.ZipFile(out) as zf:
        info = zf.getinfo("run.sh")
        mode = stat.S_IMODE(info.external_attr >> 16)
        assert mode & stat.S_IXUSR
        assert zf.read("run.sh") == (agent_dir / "run.sh").read_bytes()


def test_missing_run_sh_fails(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    (agent_dir / "run.sh").unlink()
    with pytest.raises(ZipBuildError, match="run.sh"):
        build_submission_zip(tmp_path)


def test_non_executable_run_sh_fails(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    os.chmod(agent_dir / "run.sh", 0o644)
    with pytest.raises(ZipBuildError, match="not executable"):
        build_submission_zip(tmp_path)


def test_oversized_zip_fails_and_is_removed(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    # Random data: incompressible, so the zip really exceeds the limit.
    (agent_dir / "shlepa_agent" / "big.py").write_bytes(os.urandom(11 * 1024 * 1024))
    with pytest.raises(ZipBuildError, match="10MB"):
        build_submission_zip(tmp_path)
    assert not (tmp_path / "dist" / "submission-dev.zip").exists()


def test_git_checkout_name_uses_short_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    import shlepa_cli.zip_build as zip_build

    monkeypatch.setattr(zip_build, "_git_short_sha", lambda root: "abc1234")
    out = build_submission_zip(tmp_path)
    assert out.name == "submission-abc1234.zip"


# --- Telemetry backstop (danger zone: the submission must stay telemetry-free)


FORBIDDEN_IMPORT_ROOTS = {"opentelemetry", "openinference", "mlflow"}


def _forbidden_imports(source: str) -> list[str]:
    """AST-scan a .py source for top-level import roots in FORBIDDEN_IMPORT_ROOTS.

    Catches plain, aliased, dotted, relative-guarded and nested imports —
    everything an import statement can hide. Relative imports (module is
    None) are never forbidden roots.
    """
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0 or node.module is None:
                continue  # relative import within the package
            roots = [node.module.split(".")[0]]
        else:
            continue
        found.extend(root for root in roots if root in FORBIDDEN_IMPORT_ROOTS)
    return found


def test_scan_catches_plain_and_aliased_imports() -> None:
    assert _forbidden_imports(
        "import opentelemetry.trace\n" + "from openinference.semconv import X\n"
    )
    assert _forbidden_imports("import mlflow as m\n")
    assert _forbidden_imports("if True:\n    from mlflow import log_param\n")
    assert not _forbidden_imports("import pydantic_ai\nX = 1\n")
    assert not _forbidden_imports("from . import core\n")


def test_zip_has_no_telemetry_paths_and_no_forbidden_imports(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    out = build_submission_zip(tmp_path)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert not any("telemetry" in name for name in names)
        for name in names:
            if name.endswith(".py"):
                source = zf.read(name).decode("utf-8")
                assert not _forbidden_imports(source), name


def test_zip_backstop_fails_on_telemetry_import_in_shipped_file(tmp_path: Path) -> None:
    agent_dir = tmp_path / "agent"
    _make_agent_tree(agent_dir)
    (agent_dir / "shlepa_agent" / "core.py").write_text(
        "import opentelemetry.trace  # sneaky\n"
    )
    out = build_submission_zip(tmp_path)
    with zipfile.ZipFile(out) as zf:
        source = zf.read("shlepa_agent/core.py").decode("utf-8")
    assert _forbidden_imports(source)


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_real_agent_submission_is_telemetry_free() -> None:
    """Build the zip from the real agent/ tree (the actual submission)."""
    out = build_submission_zip(REPO_ROOT)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert names  # sanity: the builder produced something
        assert not any("telemetry" in name for name in names)
        for name in names:
            if name.endswith(".py"):
                source = zf.read(name).decode("utf-8")
                assert not _forbidden_imports(source), name
