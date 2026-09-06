"""Tests for submit_test: MLflow logging + endpoint resolution (file:// store)."""

from pathlib import Path

import pytest
from mlflow import MlflowClient

from shlepa_cli import submit_test
from shlepa_cli.config import Settings


@pytest.fixture(autouse=True)
def filestore(tmp_path: Path, monkeypatch):
    # MLflow 3's file:// store keeps its sqlite metadata db in the current
    # working directory (mlflow.db); run from tmp_path to stay hermetic.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.chdir(tmp_path)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        openai_base_url="http://main/v1",
        openai_api_key="main-key",
        local_agent_model="main-model",
        ci_openai_base_url="http://ci/v1",
        ci_openai_api_key="ci-key",
        ci_model="ci-model",
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )


def _trials() -> list[submit_test.HarborTrial]:
    return [
        submit_test.HarborTrial(
            "contest-hello-file", "solved", 1.0, 100, 50, 42.5, None
        ),
        submit_test.HarborTrial(
            "contest-bye-file", "timeout", None, None, None, 300.0,
            "TimeoutError: agent exceeded 300s",
        ),
        submit_test.HarborTrial(
            "contest-err", "error", None, 10, 5, 12.0, "RuntimeError: boom"
        ),
    ]


def test_log_trials_main(tmp_path: Path) -> None:
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'mlruns'}")
    run_ids = submit_test.log_trials_to_mlflow(
        client,
        _settings(tmp_path),
        experiment="submit-test",
        model="main-model",
        endpoint_class="main",
        trials=_trials(),
    )
    assert set(run_ids) == {
        "contest-hello-file",
        "contest-bye-file",
        "contest-err",
    }
    exp = client.get_experiment_by_name("submit-test")
    assert exp is not None
    runs = {r.info.run_name: r for r in client.search_runs([exp.experiment_id])}

    solved = runs["contest-hello-file"]
    assert solved.info.status == "FINISHED"
    assert solved.data.tags["endpoint_class"] == "main"
    assert solved.data.tags["model"] == "main-model"
    assert solved.data.tags["harbor_status"] == "solved"
    assert solved.data.metrics["solved"] == 1.0
    assert solved.data.metrics["reward"] == 1.0
    assert solved.data.metrics["tokens_in"] == 100
    assert solved.data.metrics["tokens_out"] == 50
    assert solved.data.metrics["duration_sec"] == 42.5

    timeout = runs["contest-bye-file"]
    assert timeout.data.metrics["solved"] == 0.0
    assert "reward" not in timeout.data.metrics
    assert "error" not in timeout.data.params
    assert Path(client.download_artifacts(timeout.info.run_id, "data/error.txt")).read_text().startswith("TimeoutError")
    assert timeout.data.metrics["evaluation_valid"] == 0
    assert timeout.info.status == "FAILED"

    errored = runs["contest-err"]
    assert errored.data.tags["harbor_status"] == "error"
    assert errored.data.metrics["solved"] == 0.0


def test_log_trials_ci_experiment(tmp_path: Path) -> None:
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'mlruns'}")
    submit_test.log_trials_to_mlflow(
        client,
        _settings(tmp_path),
        experiment="shlepa-ci",
        model="ci-model",
        endpoint_class="ci",
        trials=_trials()[:1],
    )
    exp = client.get_experiment_by_name("shlepa-ci")
    assert exp is not None
    runs = client.search_runs([exp.experiment_id])
    assert len(runs) == 1
    assert runs[0].data.tags["endpoint_class"] == "ci"


def test_resolve_endpoint_main() -> None:
    s = _settings(Path("/nonexistent"))
    base_url, api_key, model, endpoint_class, experiment = (
        submit_test.resolve_endpoint(s, ci=False)
    )
    assert base_url == "http://main/v1"
    assert api_key == "main-key"
    assert model == "main-model"
    assert endpoint_class == "main"
    assert experiment == "submit-test"


def test_resolve_endpoint_ci() -> None:
    s = _settings(Path("/nonexistent"))
    base_url, api_key, model, endpoint_class, experiment = (
        submit_test.resolve_endpoint(s, ci=True)
    )
    assert base_url == "http://ci/v1"
    assert api_key == "ci-key"
    assert model == "ci-model"
    assert endpoint_class == "ci"
    assert experiment == "shlepa-ci"


def test_resolve_endpoint_ci_falls_back_to_main_model() -> None:
    s = _settings(Path("/nonexistent"))
    s = Settings(
        **{**s.__dict__, "ci_model": None, "ci_openai_base_url": None}
    )
    _, _, model, _, _ = submit_test.resolve_endpoint(s, ci=True)
    assert model == "main-model"  # CI model unset -> fall back to main model
