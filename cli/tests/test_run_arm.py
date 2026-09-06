"""shlepa run --arm: toolset arm selection (flag / env / MLflow tag).

Covers the CLI surface of the named-toolset A/B: flag validation, env
fallback, the AGENT_TOOLSET pass-through into the container (and
host-mode) environment, and the MLflow toolset tag.
"""

import os

import pytest
from mlflow import MlflowClient
from typer.testing import CliRunner

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.main import app
from shlepa_cli.tasks import Task

runner = CliRunner()


@pytest.fixture(autouse=True)
def _allow_file_store(monkeypatch):
    # MLflow 3.x keeps the file store in maintenance mode behind an opt-in.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


def _make_repo(base):
    (base / ".git").mkdir()
    (base / "agent").mkdir()
    exp = base / "experiments"
    exp.mkdir()
    (exp / "all.yaml").write_text("name: all\ntasks: all\n")
    task = base / "tasks" / "contest-hello-file"
    task.mkdir(parents=True)
    (task / "task.toml").write_text('schema_version = "1.2"\nname = "Hello File"\n')


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


# --- flag / env resolution (dry-run surface) --------------------------------


def test_run_dry_run_default_arm_is_baseline(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "arm: baseline" in result.output


def test_run_dry_run_arm_flag(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    result = runner.invoke(app, ["run", "--dry-run", "--arm", "+sifs"])
    assert result.exit_code == 0, result.output
    assert "arm: +sifs" in result.output


def test_run_dry_run_arm_env_fallback(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_TOOLSET", "+smart-grep")
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "arm: +smart-grep" in result.output


def test_run_dry_run_flag_beats_env(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_TOOLSET", "banana")
    result = runner.invoke(app, ["run", "--dry-run", "--arm", "baseline"])
    assert result.exit_code == 0, result.output
    assert "arm: baseline" in result.output


def test_run_invalid_arm_flag_errors(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    result = runner.invoke(app, ["run", "--dry-run", "--arm", "banana"])
    assert result.exit_code != 0
    assert "unknown toolset arm" in result.output


def test_run_invalid_arm_env_errors(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_TOOLSET", "banana")
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code != 0
    assert "unknown toolset arm" in result.output


# --- container env pass-through --------------------------------------------


def test_agent_env_includes_arm(tmp_path):
    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    env = run_engine._agent_env(_settings(tmp_path), "m", task, arm="+sifs")
    assert env["AGENT_TOOLSET"] == "+sifs"


def test_agent_env_without_arm_has_no_toolset_var(tmp_path):
    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    env = run_engine._agent_env(_settings(tmp_path), "m", task)
    assert "AGENT_TOOLSET" not in env


# --- host mode (_call_agent) ------------------------------------------------


def test_call_agent_host_mode_passes_and_cleans_arm_env(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_TOOLSET", raising=False)
    seen: dict[str, str | None] = {}

    def fake_runner(instruction, workspace, model, timeout, otel):
        seen["arm"] = os.environ.get("AGENT_TOOLSET")
        return run_engine.AgentRun("", 0, 0, 0)

    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    run_engine._call_agent(
        fake_runner, task, "hi", tmp_path, None, _settings(tmp_path), arm="+sifs"
    )
    assert seen["arm"] == "+sifs"
    # restored afterwards
    assert os.environ.get("AGENT_TOOLSET") is None


# --- MLflow toolset tag ------------------------------------------------------


def _result(tmp_path):
    return run_engine.TaskResult(
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


def test_log_task_arm_tag(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path), arm="+sifs"
    )
    assert client.get_run(run_id).data.tags["toolset"] == "+sifs"

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path)
    )
    assert "toolset" not in client.get_run(run_id).data.tags
