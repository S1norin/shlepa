"""Tests for the 'shlepa submit-test' CLI wiring (stubbed Harbor runner)."""

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shlepa_cli import main as main_module
from shlepa_cli import submit_test as submit_test_module

runner = CliRunner()


@pytest.fixture(autouse=True)
def filestore(tmp_path: Path, monkeypatch):
    # hermetic MLflow file store + repo root
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")
    monkeypatch.chdir(tmp_path)
    # Drop MLflow credentials that other tests may have leaked into the
    # environment (build_tracking_uri would fold them into file:// URIs).
    monkeypatch.delenv("MLFLOW_TRACKING_USERNAME", raising=False)
    monkeypatch.delenv("MLFLOW_TRACKING_PASSWORD", raising=False)


def _make_repo(base: Path) -> None:
    (base / ".git").mkdir()
    agent = base / "agent"
    (agent / "shlepa_agent").mkdir(parents=True)
    run_sh = agent / "run.sh"
    run_sh.write_text("#!/bin/bash\nexec python3 -m shlepa_agent \"$1\"\n")
    os.chmod(run_sh, 0o755)
    (agent / "agent.py").write_text("class MyInstalledAgent: pass\n")
    (agent / "shlepa_agent" / "__init__.py").write_text("__version__ = '1'\n")
    task = base / "tasks" / "contest-hello-file"
    (task / "tests").mkdir(parents=True)
    (task / "task.toml").write_text(
        'schema_version = "1.2"\n\n[task]\nname = "local/hello-file"\n'
    )


def _trial_result(task_name="local/hello-file", *, reward=1.0):
    return {
        "id": "22222222-2222-2222-2222-222222222222",
        "task_name": task_name,
        "trial_name": f"{task_name}-0",
        "trial_uri": "file:///x",
        "task_id": {"type": "local", "path": "tasks/contest-hello-file"},
        "task_checksum": "abc",
        "config": {},
        "agent_info": {"name": "local-openrouter-agent", "version": "unknown"},
        "agent_result": {"n_input_tokens": 11, "n_output_tokens": 7},
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": None,
        "started_at": "2026-08-26T16:04:50.546769Z",
        "finished_at": "2026-08-26T16:05:47.920424Z",
    }


def _stub_runner(tmp_path: Path, *, reward=1.0, rc=0, stderr=""):
    """Harbor stub: writes a fake job dir (trial subdir) into --jobs-dir."""
    seen: dict = {}

    def _run(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
        seen["argv"] = argv
        seen["env"] = env
        if rc != 0:
            return rc, "", stderr
        jobs_dir = Path(argv[argv.index("--jobs-dir") + 1])
        job_name = argv[argv.index("--job-name") + 1]
        trial_dir = jobs_dir / job_name / f"{job_name}__stub"
        trial_dir.mkdir(parents=True, exist_ok=True)
        (trial_dir / "result.json").write_text(
            json.dumps(_trial_result(reward=reward))
        )
        (jobs_dir / job_name / "result.json").write_text(
            json.dumps({"n_total_trials": 1})
        )
        return 0, "harbor stub ok\n", ""

    return _run, seen


def _invoke_with_runner(tmp_path, stub, monkeypatch, args) -> object:
    monkeypatch.setattr(submit_test_module, "_default_runner", stub)
    return runner.invoke(main_module.app, args, catch_exceptions=False)


def test_submit_test_cli_all_solved(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path)
    stub, seen = _stub_runner(tmp_path, reward=1.0)
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://main/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    result = _invoke_with_runner(
        tmp_path, stub, monkeypatch, ["submit-test", "contest-hello-file"]
    )
    assert result.exit_code == 0, result.output
    assert "1/1 solved" in result.output
    assert "solved: local/hello-file" in result.output
    # agent env forwarded to the in-container agent via --ae
    argv = seen["argv"]
    ae = [argv[i + 1] for i in range(len(argv) - 1) if argv[i] == "--ae"]
    assert "OPENAI_BASE_URL=http://main/v1" in ae
    assert "OPENAI_API_KEY=k" in ae
    # unzipped agent is on PYTHONPATH for the agent import
    assert str(tmp_path) in seen["env"]["PYTHONPATH"]


def test_submit_test_cli_harbor_failure(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path)
    stub, _ = _stub_runner(tmp_path, rc=1, stderr="boom traceback")
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "test-model")
    result = _invoke_with_runner(
        tmp_path, stub, monkeypatch, ["submit-test"]
    )
    assert result.exit_code == 1, result.output
    assert "harbor failed" in result.output
    assert "0/1 solved" in result.output


def test_submit_test_cli_unknown_task(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path)
    stub, _ = _stub_runner(tmp_path)
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "test-model")
    result = _invoke_with_runner(
        tmp_path, stub, monkeypatch, ["submit-test", "nope"]
    )
    assert result.exit_code == 1, result.output
    assert "unknown task(s)" in result.output


def test_submit_test_cli_no_model(tmp_path: Path, monkeypatch) -> None:
    _make_repo(tmp_path)
    stub, _ = _stub_runner(tmp_path)
    monkeypatch.delenv("LOCAL_AGENT_MODEL", raising=False)
    result = _invoke_with_runner(
        tmp_path, stub, monkeypatch, ["submit-test"]
    )
    assert result.exit_code == 1, result.output
    assert "no model configured" in result.output


def test_submit_test_cli_mlflow_logged(tmp_path: Path, monkeypatch) -> None:
    from mlflow import MlflowClient

    _make_repo(tmp_path)
    stub, _ = _stub_runner(tmp_path, reward=1.0)
    monkeypatch.setenv("LOCAL_AGENT_MODEL", "test-model")
    monkeypatch.setenv("MLFLOW_TRACKING_URI", f"file://{tmp_path / 'mlruns'}")
    result = _invoke_with_runner(
        tmp_path, stub, monkeypatch, ["submit-test"]
    )
    assert result.exit_code == 0, result.output
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'mlruns'}")
    exp = client.get_experiment_by_name("submit-test")
    assert exp is not None
    runs = client.search_runs([exp.experiment_id])
    assert len(runs) == 1
    assert runs[0].data.tags["endpoint_class"] == "main"
    assert runs[0].data.metrics["solved"] == 1.0
    assert runs[0].info.run_name == "local/hello-file"
