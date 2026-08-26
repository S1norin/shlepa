"""Tests for the submission zip builder (shlepa zip)."""

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
