"""Tests for repo root resolution and .env loading."""

from pathlib import Path

import pytest

from shlepa_cli import config


def _make_repo(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    (base / ".git").mkdir()
    (base / "agent").mkdir()
    return base


def test_find_repo_root_from_nested_dir(tmp_path):
    root = _make_repo(tmp_path / "shlepa")
    nested = root / "cli" / "shlepa_cli"
    nested.mkdir(parents=True)
    assert config.find_repo_root(nested) == root


def test_find_repo_root_from_root(tmp_path):
    root = _make_repo(tmp_path / "shlepa")
    assert config.find_repo_root(root) == root


def test_find_repo_root_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FileNotFoundError):
        config.find_repo_root(empty)


def test_load_env_loads_missing_values_only(tmp_path, monkeypatch):
    root = _make_repo(tmp_path / "shlepa")
    (root / ".env").write_text(
        "OPENAI_BASE_URL=http://from-dotenv:8080/v1\n"
        "LOCAL_AGENT_MODEL=model-from-dotenv\n"
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "http://from-env:9999/v1")
    monkeypatch.delenv("LOCAL_AGENT_MODEL", raising=False)

    returned = config.load_env(root)

    assert returned == root
    import os

    assert os.environ["OPENAI_BASE_URL"] == "http://from-env:9999/v1"
    assert os.environ["LOCAL_AGENT_MODEL"] == "model-from-dotenv"


def test_load_env_missing_file_is_ok(tmp_path):
    root = _make_repo(tmp_path / "shlepa")
    assert config.load_env(root) == root


def test_get_settings_typed_values(tmp_path, monkeypatch):
    root = _make_repo(tmp_path / "shlepa")
    (root / ".env").write_text(
        "OPENAI_API_KEY=sk-test\n"
        "MLFLOW_TRACKING_URI=https://mlflow.example\n"
        "SLEPA_OTEL_ENABLED=1\n"
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318\n"
    )
    for var in (
        "OPENAI_BASE_URL",
        "LOCAL_AGENT_MODEL",
        "CI_OPENAI_BASE_URL",
        "CI_OPENAI_API_KEY",
        "CI_MODEL",
        "MLFLOW_TRACKING_USERNAME",
        "MLFLOW_TRACKING_PASSWORD",
    ):
        monkeypatch.delenv(var, raising=False)

    settings = config.get_settings(root)

    assert settings.repo_root == root
    assert settings.openai_api_key == "sk-test"
    assert settings.mlflow_tracking_uri == "https://mlflow.example"
    assert settings.shlepa_otel_enabled is True
    assert settings.otel_exporter_otlp_endpoint == "http://localhost:4318"
    assert settings.openai_base_url is None
    assert settings.ci_model is None
