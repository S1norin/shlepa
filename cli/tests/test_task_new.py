"""Tests for 'shlepa task new' (task scaffold)."""

from pathlib import Path
from typer.testing import CliRunner

import tomllib

from shlepa_cli.main import app


def _make_repo(base: Path) -> Path:
    (base / ".git").mkdir()
    (base / "agent" / "shlepa_agent").mkdir(parents=True)
    (base / "agent" / "shlepa_agent" / "__init__.py").write_text("")
    (base / "tasks").mkdir()
    return base


def test_task_new_scaffolds_all_files(tmp_path: Path, monkeypatch):
    base = _make_repo(tmp_path)
    monkeypatch.chdir(base)
    runner = CliRunner()
    result = runner.invoke(app, ["task", "new", "own-my-new-task"])
    assert result.exit_code == 0, result.output

    task_dir = base / "tasks" / "own-my-new-task"
    parsed = tomllib.loads((task_dir / "task.toml").read_text())

    # schema + metadata
    assert parsed["schema_version"] == "1.2"
    assert parsed["task"]["name"] == "own/my-new-task"
    assert parsed["metadata"]["source"] == "own"

    # timing sections
    assert "timeout_sec" in parsed["verifier"]
    assert "timeout_sec" in parsed["agent"]
    assert "build_timeout_sec" in parsed["environment"]

    # files
    assert (task_dir / "instruction.md").is_file()
    env = task_dir / "environment" / "Dockerfile"
    assert env.is_file()
    assert "FROM secureintelligent/acp:latest" in env.read_text()
    assert (task_dir / "tests" / "test_outputs.py").is_file()
    assert (task_dir / "solution").is_dir()


def test_task_new_rejects_existing_dir(tmp_path: Path, monkeypatch):
    base = _make_repo(tmp_path)
    monkeypatch.chdir(base)
    (base / "tasks" / "own-dup").mkdir()
    runner = CliRunner()
    result = runner.invoke(app, ["task", "new", "own-dup"])
    assert result.exit_code != 0
    assert "exists" in result.output.lower()


def test_task_new_rejects_bad_names(tmp_path: Path, monkeypatch):
    base = _make_repo(tmp_path)
    monkeypatch.chdir(base)
    runner = CliRunner()
    for name in ("nosource", "wat/foo", "own-Foo-Bar", "own/", "own"):
        result = runner.invoke(app, ["task", "new", name])
        assert result.exit_code != 0, f"{name} should be rejected"
        assert not (base / "tasks" / name).exists()
