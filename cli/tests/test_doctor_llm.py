"""Doctor tests: LLM endpoint and model-match checks (s1)."""

import pytest

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


@pytest.fixture
def stub():
    server, url = start_doctor_stub()
    try:
        yield url
    finally:
        server.shutdown()
        server.server_close()


def test_endpoint_and_model_match(stub):
    settings = _settings(stub, "stub-model")
    endpoint = doctor.check_llm_endpoint(settings)
    model = doctor.check_llm_model(settings)
    assert endpoint.ok, endpoint.detail
    assert model.ok, model.detail


def test_model_mismatch_names_both(stub):
    settings = _settings(stub, "some-other-model")
    result = doctor.check_llm_model(settings)
    assert not result.ok
    assert "some-other-model" in result.detail
    assert "stub-model" in result.detail


def test_endpoint_down_is_clean_failure():
    # Nothing listens on this port.
    settings = _settings("http://127.0.0.1:1/v1", "stub-model")
    result = doctor.check_llm_endpoint(settings)
    assert not result.ok
    assert result.detail


def test_missing_endpoint_config_fails_cleanly():
    settings = _settings(None, "stub-model")
    assert not doctor.check_llm_endpoint(settings).ok
    assert not doctor.check_llm_model(settings).ok
