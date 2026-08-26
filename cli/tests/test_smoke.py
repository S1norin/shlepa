"""Tests for shlepa smoke (stage logic with stubs + file:// MLflow, CLI wiring)."""

from pathlib import Path
from typer.testing import CliRunner
from unittest.mock import patch

import pytest

from shlepa_cli import smoke as smoke_module
from shlepa_cli.config import Settings
from shlepa_cli.doctor import CheckResult
from shlepa_cli.main import app
from shlepa_cli.run_engine import TaskResult

SMOKE_SLUG = "contest-hello-file"


@pytest.fixture(autouse=True)
def filestore(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.chdir(tmp_path)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        openai_base_url="http://llm.test/v1",
        openai_api_key="sk-test",
        local_agent_model="test-model",
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=f"file://{tmp_path / 'ml'}",
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )


def _doctor_results(ok: bool) -> list[CheckResult]:
    return [
        CheckResult("llm_endpoint", ok, "detail"),
        CheckResult("llm_model", ok, "detail"),
        CheckResult("mlflow", ok, "detail"),
        CheckResult("docker", ok, "detail"),
    ]


def _task_result(tmp_path: Path, ok=True, solved=True, error=None) -> TaskResult:
    return TaskResult(
        slug=SMOKE_SLUG,
        ok=ok,
        solved=solved,
        duration_sec=1.25,
        tokens_in=3,
        tokens_out=4,
        tokens_total=7,
        tool_calls=2,
        final_output="done",
        error=error,
        score_detail="reward=1" if solved else "reward=0",
        workspace=tmp_path,
    )


def test_smoke_all_stages_pass(tmp_path: Path):
    reports: list[str] = []
    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path),
    )
    assert ok
    assert reports[0] == "doctor: ok"
    assert any("task: ok" in r and SMOKE_SLUG in r for r in reports)
    assert any(r.startswith("mlflow: ok") for r in reports)


def test_smoke_doctor_failure_stops(tmp_path: Path):
    reports: list[str] = []
    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(False),
        task_result=_task_result(tmp_path),
    )
    assert not ok
    assert reports[0].startswith("doctor: FAIL")
    assert not any(r.startswith("task:") for r in reports)
    assert not any(r.startswith("mlflow:") for r in reports)


def test_smoke_task_hard_error(tmp_path: Path):
    reports: list[str] = []
    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path, ok=False, solved=False, error="boom"),
    )
    assert not ok
    assert "task: FAIL" in reports[1]
    assert "boom" in reports[1]
    # The failed task result is still logged for CI diagnostics.
    assert any(r.startswith("mlflow: ok") for r in reports)
    from shlepa_cli.mlflow_client import get_mlflow_client

    client = get_mlflow_client(_settings(tmp_path))
    exp = client.get_experiment_by_name("smoke")
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=f"run_name = '{SMOKE_SLUG}'",
    )
    assert len(runs) == 1
    assert runs[0].info.status == "FINISHED"
    assert runs[0].data.metrics["solved"] == 0.0


def test_smoke_task_unsolved(tmp_path: Path):
    reports: list[str] = []
    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path, solved=False),
    )
    assert not ok
    assert reports[1].startswith("task: FAIL")
    assert "unsolved" in reports[1]
    # The unsolved task result is still logged for CI diagnostics.
    assert any(r.startswith("mlflow: ok") for r in reports)


def test_smoke_mlflow_failure(tmp_path: Path):
    reports: list[str] = []

    class BoomClient:
        def get_experiment_by_name(self, name):
            raise RuntimeError("mlflow down")

    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path),
        mlflow_client=BoomClient(),
    )
    assert not ok
    assert reports[2].startswith("mlflow: FAIL")
    assert "mlflow down" in reports[2]


def test_smoke_mlflow_run_is_queryable(tmp_path: Path):
    reports: list[str] = []
    ok = smoke_module.run_smoke(
        _settings(tmp_path),
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path),
    )
    assert ok
    # The mlflow stage must have verified a FINISHED run for the task.
    from shlepa_cli.mlflow_client import get_mlflow_client

    client = get_mlflow_client(_settings(tmp_path))
    exp = client.get_experiment_by_name("smoke")
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=f"run_name = '{SMOKE_SLUG}'",
    )
    assert len(runs) == 1
    assert runs[0].info.status == "FINISHED"


def _ci_settings(tmp_path: Path, **overrides) -> Settings:
    import dataclasses

    base = _settings(tmp_path)
    values = {
        "ci_openai_base_url": "http://ci-llm.test/v1",
        "ci_openai_api_key": "sk-ci",
        "ci_model": "ci-model",
    }
    values.update(overrides)
    return dataclasses.replace(base, **values)


def test_smoke_ci_logs_to_shlepa_ci(tmp_path: Path):
    reports: list[str] = []
    settings = _ci_settings(tmp_path)
    ok = smoke_module.run_smoke(
        settings,
        ci=True,
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path),
    )
    assert ok
    from shlepa_cli.mlflow_client import get_mlflow_client

    client = get_mlflow_client(settings)
    exp = client.get_experiment_by_name("shlepa-ci")
    assert exp is not None, "CI smoke must land in the shlepa-ci experiment"
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=f"run_name = '{SMOKE_SLUG}'",
    )
    assert len(runs) == 1
    assert runs[0].data.tags["endpoint_class"] == "ci"
    assert runs[0].data.tags["model"] == "ci-model"


def test_smoke_ci_falls_back_to_main_model(tmp_path: Path):
    reports: list[str] = []
    settings = _ci_settings(tmp_path, ci_model=None)
    ok = smoke_module.run_smoke(
        settings,
        ci=True,
        out=reports.append,
        doctor_results=_doctor_results(True),
        task_result=_task_result(tmp_path),
    )
    assert ok
    from shlepa_cli.mlflow_client import get_mlflow_client

    client = get_mlflow_client(settings)
    exp = client.get_experiment_by_name("shlepa-ci")
    runs = client.search_runs(
        experiment_ids=[exp.experiment_id],
        filter_string=f"run_name = '{SMOKE_SLUG}'",
    )
    assert len(runs) == 1
    assert runs[0].data.tags["model"] == "test-model"


def test_cli_smoke_ci_flag(tmp_path: Path):
    from shlepa_cli import config as config_module

    seen: dict = {}

    def fake_run_smoke(settings, *, ci, **kwargs):
        seen["ci"] = ci
        return True

    runner = CliRunner()
    with (
        patch.object(smoke_module, "run_smoke", side_effect=fake_run_smoke),
        patch.object(config_module, "get_settings", return_value=_settings(tmp_path)),
    ):
        result = runner.invoke(app, ["smoke", "--ci"])
    assert result.exit_code == 0
    assert seen["ci"] is True


def test_cli_smoke_exit_codes(tmp_path: Path):
    from shlepa_cli import config as config_module

    runner = CliRunner()
    with (
        patch.object(smoke_module, "run_smoke", return_value=True),
        patch.object(config_module, "get_settings", return_value=_settings(tmp_path)),
    ):
        result = runner.invoke(app, ["smoke"])
    assert result.exit_code == 0
    with (
        patch.object(smoke_module, "run_smoke", return_value=False),
        patch.object(config_module, "get_settings", return_value=_settings(tmp_path)),
    ):
        result = runner.invoke(app, ["smoke"])
    assert result.exit_code == 1
