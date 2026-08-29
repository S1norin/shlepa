"""Run engine tests: preset batch loop + summary (s5)."""

from mlflow import MlflowClient

import pytest

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.tasks import Preset, Task


@pytest.fixture(autouse=True)
def _allow_file_store(monkeypatch):
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


def _task(root, slug, content_ok=True):
    task_dir = root / "tasks" / slug
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "instruction.md").write_text("Create a file.")
    expected = "out" if content_ok else "other"
    (task_dir / "tests" / "test_check.py").write_text(
        "import os, pathlib\n\n"
        "def test_f():\n"
        "    ws = pathlib.Path(os.environ['SLEPA_WORKSPACE'])\n"
        f"    assert (ws / 'out.txt').read_text() == {expected!r}\n"
    )
    return Task(slug=slug, name=slug, path=task_dir, timeout_sec=60)


def test_batch_continues_after_agent_error(tmp_path):
    tasks = [_task(tmp_path, "boom"), _task(tmp_path, "fine")]
    preset = Preset(name="all", tasks="all")
    results = run_engine.run_preset(
        _settings(tmp_path),
        preset,
        tasks,
        model="m",
        no_docker=True,
        agent_runner=_agent_for(None),
    )
    assert len(results) == 2
    assert not results[0].ok
    assert "agent crashed" in (results[0].error or "")
    assert results[1].ok
    assert results[1].solved


def _agent_for(workdir_hint):
    # pick agent by which task's workspace is being written
    def runner(instruction, workdir, model, timeout_sec, otel):
        if "boom" in workdir.name:
            raise RuntimeError("agent crashed")
        (workdir / "out.txt").write_text("out")
        return run_engine.AgentRun("done", 5, 3, 1)

    return runner


def test_format_summary(tmp_path):
    r1 = run_engine.TaskResult(
        slug="contest-a", ok=True, solved=True, duration_sec=12.5,
        tokens_in=10, tokens_out=5, tokens_total=15, tool_calls=2,
        final_output="done", error=None, score_detail="", workspace=tmp_path,
    )
    r2 = run_engine.TaskResult(
        slug="contest-b", ok=True, solved=False, duration_sec=3.2,
        tokens_in=4, tokens_out=2, tokens_total=6, tool_calls=0,
        final_output="", error=None, score_detail="", workspace=tmp_path,
    )
    summary = run_engine.format_summary([r1, r2])
    assert "contest-a" in summary
    assert "contest-b" in summary
    assert "1/2 solved" in summary
    assert "unsolved" in summary


def test_run_preset_logs_mlflow(tmp_path):
    tasks = [_task(tmp_path, "ok-task")]
    preset = Preset(name="exp1", tasks="all")
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'store'}")
    run_engine.run_preset(
        _settings(tmp_path),
        preset,
        tasks,
        model="m",
        no_docker=True,
        agent_runner=_agent_for(None),
        mlflow_client=client,
    )
    # Runs land in the task-family experiment (slug 'ok-task' -> 'ok'),
    # not the preset-named one; the preset is kept as a tag.
    exp = client.get_experiment_by_name("ok")
    assert exp is not None
    runs = client.search_runs([exp.experiment_id])
    assert len(runs) == 1
    assert runs[0].data.metrics["solved"] == 1.0
    assert runs[0].data.tags["preset"] == "exp1"
