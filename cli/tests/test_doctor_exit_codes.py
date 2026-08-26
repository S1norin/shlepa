"""Doctor CLI-level tests: exit codes (mismatch -> 2, other -> 1)."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from doctor_stub import start_doctor_stub
from shlepa_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _hermetic_repo(tmp_path: Path, monkeypatch):
    """Run against a fake repo so the real .env (credentials) is never
    loaded, and drop MLflow vars leaked by other tests."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "agent").mkdir()
    monkeypatch.chdir(tmp_path)
    for var in ("MLFLOW_TRACKING_URI", "MLFLOW_TRACKING_USERNAME",
                "MLFLOW_TRACKING_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


def test_exit_2_on_model_mismatch(monkeypatch):
    server, url = start_doctor_stub()
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "some-other-model")
    try:
        result = runner.invoke(app, ["doctor"])
    finally:
        server.shutdown()
        server.server_close()
    assert result.exit_code == 2
    assert "mismatch" in result.output


def test_exit_1_on_other_failure(monkeypatch):
    server, url = start_doctor_stub()
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "stub-model")
    try:
        result = runner.invoke(app, ["doctor"])
    finally:
        server.shutdown()
        server.server_close()
    # LLM checks pass; MLflow is not configured -> overall failure, code 1.
    assert result.exit_code == 1
    assert "FAIL  mlflow" in result.output
