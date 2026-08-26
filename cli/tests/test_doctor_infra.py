"""Doctor tests: MLflow and docker checks (s2)."""

from pathlib import Path

from shlepa_cli import doctor
from shlepa_cli.config import Settings


def _settings(**overrides):
    base = dict(
        repo_root=Path("."),
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model=None,
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )
    base.update(overrides)
    return Settings(**base)


class _FakeMlflowClient:
    def __init__(self, version="3.15.1"):
        self.version = version
        self.calls = 0

    def get_version(self):
        self.calls += 1
        return self.version


def test_mlflow_ok_with_fake_client():
    settings = _settings(mlflow_tracking_uri="https://mlflow.example")
    client = _FakeMlflowClient()

    def factory(s):
        return client

    result = doctor.check_mlflow(settings, client_factory=factory)
    assert result.ok, result.detail
    assert "3.15.1" in result.detail
    assert client.calls == 1


def test_mlflow_missing_uri():
    result = doctor.check_mlflow(_settings())
    assert not result.ok
    assert "MLFLOW_TRACKING_URI" in result.detail


def test_mlflow_unreachable_reported():
    settings = _settings(mlflow_tracking_uri="https://mlflow.example")

    def factory(s):
        raise RuntimeError("connection refused")

    result = doctor.check_mlflow(settings, client_factory=factory)
    assert not result.ok
    assert "connection refused" in result.detail


def test_docker_binary_missing(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    result = doctor.check_docker(_settings())
    assert not result.ok
    assert "not found" in result.detail


def test_docker_ok(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")

    class _Proc:
        returncode = 0
        stdout = "29.5.2\n"
        stderr = ""

    monkeypatch.setattr(
        doctor.subprocess, "run", lambda *a, **k: _Proc()
    )
    result = doctor.check_docker(_settings())
    assert result.ok, result.detail
    assert "29.5.2" in result.detail


def test_docker_daemon_down(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/docker")

    class _Proc:
        returncode = 1
        stdout = ""
        stderr = "Cannot connect to the Docker daemon"

    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc())
    result = doctor.check_docker(_settings())
    assert not result.ok
    assert "daemon" in result.detail
