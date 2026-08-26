"""Tests for the MLflow client helper (offline)."""

from pathlib import Path

import pytest

from shlepa_cli.config import Settings
from shlepa_cli.mlflow_client import build_tracking_uri, get_mlflow_client


def _settings(**overrides) -> Settings:
    base = {
        "repo_root": Path("."),
        "openai_base_url": None,
        "openai_api_key": None,
        "local_agent_model": None,
        "ci_openai_base_url": None,
        "ci_openai_api_key": None,
        "ci_model": None,
        "mlflow_tracking_uri": None,
        "mlflow_tracking_username": None,
        "mlflow_tracking_password": None,
        "shlepa_otel_enabled": False,
        "otel_exporter_otlp_endpoint": None,
    }
    base.update(overrides)
    return Settings(**base)


def test_build_tracking_uri_with_credentials():
    uri = build_tracking_uri(
        "https://mlflow.example/api/2.0", "user", "pass"
    )
    assert uri == "https://user:pass@mlflow.example/api/2.0"


def test_build_tracking_uri_with_port():
    uri = build_tracking_uri("http://host:5000/", "u", "p")
    assert uri == "http://u:p@host:5000/"


def test_build_tracking_uri_without_credentials_unchanged():
    uri = build_tracking_uri("https://mlflow.example/", None, None)
    assert uri == "https://mlflow.example/"


def test_build_tracking_uri_special_chars_are_quoted():
    uri = build_tracking_uri("https://mlflow.example/", "u/x", "p w")
    assert uri == "https://u%2Fx:p%20w@mlflow.example/"


def test_get_mlflow_client_requires_uri():
    with pytest.raises(ValueError, match="MLFLOW_TRACKING_URI"):
        get_mlflow_client(_settings())


def test_get_mlflow_client_builds_client():
    settings = _settings(
        mlflow_tracking_uri="https://mlflow.example",
        mlflow_tracking_username="user",
        mlflow_tracking_password="pass",
    )
    client = get_mlflow_client(settings)
    assert "user:pass@mlflow.example" in client.tracking_uri
