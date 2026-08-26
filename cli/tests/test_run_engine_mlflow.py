"""Run engine tests: MLflow run logging (file:// store)."""

import pytest

from mlflow import MlflowClient

from shlepa_cli import run_engine
from shlepa_cli.config import Settings


@pytest.fixture(autouse=True)
def _allow_file_store(monkeypatch):
    # MLflow 3.x keeps the file store in maintenance mode behind an opt-in.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


def _settings(root):
    return Settings(
        repo_root=root,
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


def _result(tmp_path, **overrides):
    base = dict(
        slug="contest-hello-file",
        ok=True,
        solved=True,
        duration_sec=1.25,
        tokens_in=10,
        tokens_out=5,
        tokens_total=15,
        tool_calls=2,
        final_output="Created hello.txt",
        error=None,
        score_detail="",
        workspace=tmp_path,
    )
    base.update(overrides)
    return run_engine.TaskResult(**base)


def test_log_task_to_mlflow_file_store(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)
    (tmp_path / "result.json").write_text("{}")

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "stub-model", _result(tmp_path)
    )

    run = client.get_run(run_id)
    assert run.data.metrics["solved"] == 1.0
    assert run.data.metrics["duration_sec"] == 1.25
    assert run.data.metrics["tokens_in"] == 10
    assert run.data.metrics["tokens_out"] == 5
    assert run.data.metrics["tokens_total"] == 15
    assert run.data.metrics["tool_calls"] == 2
    assert run.data.tags["preset"] == "all"
    assert run.data.tags["model"] == "stub-model"
    assert run.data.tags["endpoint_class"] == "main"
    assert run.data.params["final_output"] == "Created hello.txt"
    # Experiment name == preset name, run name == task slug.
    assert client.get_experiment(run.info.experiment_id).name == "all"
    assert run.info.run_name == "contest-hello-file"


def test_log_task_unsolved_metrics(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "quick", None, _result(tmp_path, solved=False)
    )

    run = client.get_run(run_id)
    assert run.data.metrics["solved"] == 0.0
    assert run.data.tags["model"] == "env"
    assert client.get_experiment(run.info.experiment_id).name == "quick"


def test_log_task_logs_error_param(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client,
        settings,
        "all",
        "m",
        _result(tmp_path, ok=False, solved=False, error="boom"),
    )

    run = client.get_run(run_id)
    assert run.data.params["error"] == "boom"
    assert run.data.metrics["solved"] == 0.0
