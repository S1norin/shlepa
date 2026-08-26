"""Tests for 'shlepa clean' (tmp/ workspace cleanup)."""

import os
import time
from pathlib import Path
from typer.testing import CliRunner

from shlepa_cli import clean as clean_module
from shlepa_cli.main import app


def _make_repo(base: Path) -> Path:
    (base / ".git").mkdir()
    (base / "agent" / "shlepa_agent").mkdir(parents=True)
    (base / "agent" / "shlepa_agent" / "__init__.py").write_text("")
    (base / "tmp").mkdir()
    (base / "tmp" / "README.md").write_text("keep me\n")
    return base


def test_clean_removes_only_stale(tmp_path: Path):
    base = _make_repo(tmp_path)
    tmp = base / "tmp"
    old = tmp / "20200101-old"
    old.mkdir()
    (old / "result.json").write_text("{}")
    old_file = tmp / "old.log"
    old_file.write_text("x")
    fresh = tmp / "29990101-fresh"
    fresh.mkdir()
    now = time.time()
    os.utime(old, (now - 8 * 86400, now - 8 * 86400))
    os.utime(old_file, (now - 9 * 86400, now - 9 * 86400))

    removed = clean_module.clean(tmp, now=now)

    assert {p.name for p in removed} == {"20200101-old", "old.log"}
    assert not old.exists()
    assert not old_file.exists()
    assert fresh.exists()
    assert (tmp / "README.md").is_file()  # never touched


def test_clean_fresh_entries_kept(tmp_path: Path):
    base = _make_repo(tmp_path)
    tmp = base / "tmp"
    fresh = tmp / "now"
    fresh.mkdir()
    now = time.time()
    os.utime(fresh, (now - 86400, now - 86400))  # 1 day < 7

    assert clean_module.clean(tmp, now=now) == []
    assert fresh.exists()


def test_clean_missing_tmp_dir(tmp_path: Path):
    assert clean_module.clean(tmp_path / "nope") == []


def test_cli_clean(tmp_path: Path, monkeypatch):
    base = _make_repo(tmp_path)
    old = base / "tmp" / "20200101-old"
    old.mkdir()
    now = time.time()
    os.utime(old, (now - 30 * 86400, now - 30 * 86400))
    monkeypatch.chdir(base)
    runner = CliRunner()
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 0, result.output
    assert "20200101-old" in result.output
    assert not old.exists()
    assert (base / "tmp" / "README.md").is_file()


def test_cli_clean_nothing_to_remove(tmp_path: Path, monkeypatch):
    base = _make_repo(tmp_path)
    monkeypatch.chdir(base)
    runner = CliRunner()
    result = runner.invoke(app, ["clean"])
    assert result.exit_code == 0, result.output
    assert "nothing" in result.output
