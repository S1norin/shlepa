"""Doctor CLI-level tests: exit codes (mismatch -> 2, other -> 1)."""

from typer.testing import CliRunner

from doctor_stub import start_doctor_stub
from shlepa_cli.main import app

runner = CliRunner()


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
