"""shlepa zip: CLI command tests (builder runs against a fake repo)."""

import os
from pathlib import Path

from typer.testing import CliRunner

from shlepa_cli.main import app

runner = CliRunner()


def _make_agent_repo(base: Path) -> None:
    (base / ".git").mkdir()
    agent = base / "agent"
    (agent / "shlepa_agent").mkdir(parents=True)
    (agent / "shlepa_agent" / "telemetry").mkdir()
    run_sh = agent / "run.sh"
    run_sh.write_text("#!/bin/bash\nexec python3 -m shlepa_agent \"$1\"\n")
    os.chmod(run_sh, 0o755)
    (agent / "agent.py").write_text("print('agent')\n")
    (agent / "shlepa_agent" / "__init__.py").write_text("")
    (agent / "shlepa_agent" / "core.py").write_text("")
    (agent / "shlepa_agent" / "telemetry" / "__init__.py").write_text("")


def test_zip_command_builds_and_reports(tmp_path: Path, monkeypatch) -> None:
    _make_agent_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["zip"])

    assert result.exit_code == 0, result.output
    assert "submission-dev.zip" in result.output
    out = tmp_path / "dist" / "submission-dev.zip"
    assert out.exists()
    assert "bytes" in result.output


def test_zip_command_reports_build_error(tmp_path: Path, monkeypatch) -> None:
    _make_agent_repo(tmp_path)
    (tmp_path / "agent" / "run.sh").unlink()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["zip"])

    assert result.exit_code == 1
    assert "run.sh" in result.output
