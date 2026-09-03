"""shlepa run --loop: pipeline regime selection (flag / env / MLflow tag).

Covers the CLI surface of the loop axis (orthogonal to the toolset arm):
flag validation, SHLEPA_LOOP env fallback, the SHLEPA_LOOP pass-through
into the container (and host-mode) environment, and the MLflow loop tag
(v3 only — the default cycles regime carries no loop tag).
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


def test_run_dry_run_default_loop_is_cycles(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHLEPA_LOOP", raising=False)
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "loop: cycles" in result.output


def test_run_dry_run_loop_flag(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHLEPA_LOOP", raising=False)
    result = runner.invoke(app, ["run", "--dry-run", "--loop", "v3"])
    assert result.exit_code == 0, result.output
    assert "loop: v3" in result.output


def test_run_dry_run_loop_env_fallback(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHLEPA_LOOP", "v3")
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "loop: v3" in result.output


def test_run_dry_run_flag_beats_env(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHLEPA_LOOP", "v3")
    result = runner.invoke(app, ["run", "--dry-run", "--loop", "cycles"])
    assert result.exit_code == 0, result.output
    assert "loop: cycles" in result.output


def test_run_invalid_loop_flag_errors(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SHLEPA_LOOP", raising=False)
    result = runner.invoke(app, ["run", "--dry-run", "--loop", "banana"])
    assert result.exit_code != 0
    assert "unknown loop regime" in result.output


def test_run_invalid_loop_env_errors(tmp_path, monkeypatch):
    _make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHLEPA_LOOP", "banana")
    result = runner.invoke(app, ["run", "--dry-run"])
    assert result.exit_code != 0
    assert "unknown loop regime" in result.output


# --- container env pass-through --------------------------------------------


def test_agent_env_includes_loop(tmp_path):
    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    env = run_engine._agent_env(_settings(tmp_path), "m", task, loop="v3")
    assert env["SHLEPA_LOOP"] == "v3"


def test_agent_env_cycles_loop_has_no_var(tmp_path):
    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    env = run_engine._agent_env(_settings(tmp_path), "m", task, loop="cycles")
    assert "SHLEPA_LOOP" not in env


def test_agent_env_without_loop_has_no_var(tmp_path):
    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    env = run_engine._agent_env(_settings(tmp_path), "m", task)
    assert "SHLEPA_LOOP" not in env


# --- host mode (_call_agent) ------------------------------------------------


def test_call_agent_host_mode_passes_and_cleans_loop_env(tmp_path, monkeypatch):
    monkeypatch.delenv("SHLEPA_LOOP", raising=False)
    seen: dict[str, str | None] = {}

    def fake_runner(instruction, workspace, model, timeout, otel):
        seen["loop"] = os.environ.get("SHLEPA_LOOP")
        return run_engine.AgentRun("", 0, 0, 0)

    task = Task(slug="contest-hello-file", name="Hello", path=tmp_path)
    run_engine._call_agent(
        fake_runner, task, "hi", tmp_path, None, _settings(tmp_path), loop="v3"
    )
    assert seen["loop"] == "v3"
    # restored afterwards
    assert os.environ.get("SHLEPA_LOOP") is None


# --- MLflow loop tag ---------------------------------------------------------


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


def test_log_task_loop_tag(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path), loop="v3"
    )
    assert client.get_run(run_id).data.tags["loop"] == "v3"

    # the default cycles regime (and an explicit cycles) carry no loop tag
    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path)
    )
    assert "loop" not in client.get_run(run_id).data.tags

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path), loop="cycles"
    )
    assert "loop" not in client.get_run(run_id).data.tags
