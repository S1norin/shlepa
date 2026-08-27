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
    def __init__(self):
        self.calls = 0

    def search_experiments(self, max_results: int = 100, **kwargs):
        self.calls += 1
        return []


def test_mlflow_ok_with_fake_client():
    settings = _settings(mlflow_tracking_uri="https://mlflow.example")
    client = _FakeMlflowClient()

    def factory(s):
        return client

    result = doctor.check_mlflow(settings, client_factory=factory)
    assert result.ok, result.detail
    assert "reachable" in result.detail
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


# --- MLflow OTLP probe -----------------------------------------------------


def _raise():
    raise AssertionError("no HTTP call expected")


class _FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


def _otel_settings(**overrides):
    base = dict(
        mlflow_tracking_uri="https://ml.example",
        mlflow_tracking_username="user",
        mlflow_tracking_password="secret-pass",
        shlepa_otel_enabled=True,
        mlflow_telemetry_experiment_id="21",
    )
    base.update(overrides)
    return _settings(**base)


def test_otlp_probe_skipped_when_otel_disabled(monkeypatch):
    monkeypatch.setattr(doctor.httpx, "get", _raise)
    monkeypatch.setattr(doctor.httpx, "post", _raise)
    result = doctor.check_mlflow_otlp(_settings())
    assert result.ok
    assert "skipped" in result.detail


def test_otlp_probe_missing_uri(monkeypatch):
    result = doctor.check_mlflow_otlp(_settings(shlepa_otel_enabled=True))
    assert not result.ok
    assert "MLFLOW_TRACKING_URI" in result.detail


def test_otlp_probe_ok(monkeypatch):
    calls = {}

    def fake_get(url, headers=None, timeout=None):
        calls["get"] = (url, headers)
        return _FakeResponse(200, "3.15.1")

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post"] = (url, headers, json)
        return _FakeResponse(200)

    monkeypatch.setattr(doctor.httpx, "get", fake_get)
    monkeypatch.setattr(doctor.httpx, "post", fake_post)
    result = doctor.check_mlflow_otlp(_otel_settings())
    assert result.ok, result.detail
    assert "3.15.1" in result.detail
    get_url, get_headers = calls["get"]
    assert get_url == "https://ml.example/version"
    assert get_headers.get("Authorization", "").startswith("Basic ")
    post_url, post_headers, payload = calls["post"]
    assert post_url == "https://ml.example/v1/traces"
    assert post_headers.get("x-mlflow-experiment-id") == "21"
    blob = str(get_headers) + str(post_headers) + result.detail
    assert "secret-pass" not in blob
    assert payload["resourceSpans"]


def test_otlp_probe_version_401(monkeypatch):
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **k: _FakeResponse(401))
    monkeypatch.setattr(doctor.httpx, "post", _raise)
    result = doctor.check_mlflow_otlp(_otel_settings())
    assert not result.ok
    assert "401" in result.detail


def test_otlp_probe_post_401(monkeypatch):
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **k: _FakeResponse(200, "3.15.1"))
    monkeypatch.setattr(doctor.httpx, "post", lambda *a, **k: _FakeResponse(401))
    result = doctor.check_mlflow_otlp(_otel_settings())
    assert not result.ok
    assert "/v1/traces" in result.detail


def test_otlp_probe_no_experiment_id_skips_post(monkeypatch):
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **k: _FakeResponse(200, "3.15.1"))
    monkeypatch.setattr(doctor.httpx, "post", _raise)
    result = doctor.check_mlflow_otlp(_otel_settings(mlflow_telemetry_experiment_id=None))
    assert result.ok
    assert "skipped" in result.detail


def test_otlp_probe_included_in_run_doctor(monkeypatch):
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **k: _FakeResponse(200, "3.15.1"))
    monkeypatch.setattr(
        doctor.httpx, "post", lambda *a, **k: _FakeResponse(200)
    )
    settings = _settings(
        mlflow_tracking_uri="https://ml.example",
        shlepa_otel_enabled=True,
        mlflow_telemetry_experiment_id="21",
    )
    results, _ = doctor.run_doctor(settings, client_factory=lambda s: _FakeMlflowClient())
    names = [r.name for r in results]
    assert "mlflow_otlp" in names
