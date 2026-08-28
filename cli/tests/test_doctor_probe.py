"""Doctor tests: --probe chat completion (s3)."""

from doctor_stub import start_doctor_stub
from shlepa_cli import doctor
from shlepa_cli.config import Settings


def _settings(base_url, model):
    return Settings(
        repo_root=None,
        openai_base_url=base_url,
        openai_api_key="sk-test",
        local_agent_model=model,
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )


def test_probe_prints_self_reported_model():
    server, url = start_doctor_stub()
    try:
        info = doctor.probe_chat(_settings(url, "stub-model"))
    finally:
        server.shutdown()
        server.server_close()
    assert info.startswith("ok")
    assert "model=stub-model-actual" in info


def test_probe_failure_never_raises():
    info = doctor.probe_chat(_settings("http://127.0.0.1:1/v1", "stub-model"))
    assert info.startswith("failed")


def test_probe_skipped_without_endpoint():
    info = doctor.probe_chat(_settings(None, "stub-model"))
    assert info.startswith("skipped")


def test_run_doctor_probe_flag():
    server, url = start_doctor_stub()
    try:
        results, probe_info = doctor.run_doctor(
            _settings(url, "stub-model"), probe=True
        )
    finally:
        server.shutdown()
        server.server_close()
    assert probe_info is not None and probe_info.startswith("ok")
    assert len(results) == 5

    results, probe_info = doctor.run_doctor(_settings(url, "stub-model"))
    assert probe_info is None
