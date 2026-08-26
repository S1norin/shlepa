"""Tests for shlepa zip --register (MLflow model registry, file:// store)."""

import os
import tarfile
from pathlib import Path

import pytest

from shlepa_cli.config import Settings
from shlepa_cli.mlflow_client import get_mlflow_client
from shlepa_cli.zip_build import build_submission_zip


@pytest.fixture(autouse=True)
def filestore(monkeypatch):
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


def _make_agent_repo(base: Path) -> None:
    (base / ".git").mkdir()
    agent = base / "agent"
    (agent / "shlepa_agent" / "telemetry").mkdir(parents=True)
    run_sh = agent / "run.sh"
    run_sh.write_text("#!/bin/bash\nexec python3 -m shlepa_agent \"$1\"\n")
    os.chmod(run_sh, 0o755)
    (agent / "agent.py").write_text("print('agent')\n")
    (agent / "shlepa_agent" / "__init__.py").write_text("__version__ = '0.1.0'\n")
    (agent / "shlepa_agent" / "core.py").write_text("X = 1\n")
    (agent / "shlepa_agent" / "telemetry" / "__init__.py").write_text("T = 1\n")
    (agent / "pyproject.toml").write_text("[project]\n")


def _settings(tmp_path: Path, uri: str) -> Settings:
    return Settings(
        repo_root=tmp_path,
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model="test-model",
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=uri,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )


def test_register_creates_version_with_artifacts_and_tags(
    tmp_path: Path, monkeypatch
) -> None:
    from shlepa_cli import zip_build
    from shlepa_cli.zip_register import register_submission

    monkeypatch.setattr(zip_build, "_git_short_sha", lambda root: "abc1234")
    _make_agent_repo(tmp_path)
    uri = f"file://{tmp_path / 'ml'}"
    settings = _settings(tmp_path, uri)
    client = get_mlflow_client(settings)
    zip_path = build_submission_zip(tmp_path)

    version = register_submission(client, settings, zip_path)

    assert version == "1"
    tags = client.get_model_version("shlepa", "1").tags
    assert tags["git_sha"] == "abc1234"
    assert tags["model"] == "test-model"

    mv = client.get_model_version("shlepa", "1")
    run_id = mv.source.split("/")[-1]
    artifact_names = {a.path for a in client.list_artifacts(run_id)}
    assert "submission-abc1234.zip" in artifact_names
    tar_name = "submission-abc1234.agent.tar.gz"
    assert tar_name in artifact_names

    # The tarball is the full agent source (telemetry included, for diffs).
    local_tar = client.download_artifacts(run_id, tar_name)
    with tarfile.open(local_tar, "r:gz") as tf:
        names = set(tf.getnames())
    assert "agent/run.sh" in names
    assert "agent/shlepa_agent/core.py" in names
    assert "agent/shlepa_agent/telemetry/__init__.py" in names
    assert "agent/pyproject.toml" in names


def test_register_second_run_bumps_version(tmp_path: Path, monkeypatch) -> None:
    from shlepa_cli import zip_build
    from shlepa_cli.zip_register import register_submission

    monkeypatch.setattr(zip_build, "_git_short_sha", lambda root: "def5678")
    _make_agent_repo(tmp_path)
    uri = f"file://{tmp_path / 'ml'}"
    settings = _settings(tmp_path, uri)
    client = get_mlflow_client(settings)

    zip1 = build_submission_zip(tmp_path)
    assert register_submission(client, settings, zip1) == "1"
    # A second registration of the same artifact set bumps the version.
    assert register_submission(client, settings, zip1) == "2"
