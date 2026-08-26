"""Run engine tests: workspace + no-docker orchestration (s1)."""

import json
import os
import re

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.tasks import Task


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


def _hello_task(root, slug="contest-hello-file"):
    task_dir = root / "tasks" / slug
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "instruction.md").write_text(
        "Create hello.txt with the exact content hello"
    )
    (task_dir / "tests" / "test_check.py").write_text(
        "import os, pathlib\n\n"
        "def test_hello():\n"
        "    ws = pathlib.Path(os.environ['SLEPA_WORKSPACE'])\n"
        "    assert (ws / 'hello.txt').read_text() == 'hello'\n"
    )
    return Task(
        slug=slug,
        name="Hello File",
        path=task_dir,
        difficulty="easy",
        timeout_sec=120,
    )


def test_make_workspace_layout(tmp_path):
    ws = run_engine.make_workspace(tmp_path, "contest-hello-file")
    assert ws.is_dir()
    assert ws.parent == tmp_path / "tmp"
    assert re.fullmatch(r"\d{8}-\d{6}-contest-hello-file", ws.name)


def test_run_task_solved(tmp_path):
    task = _hello_task(tmp_path)
    settings = _settings(tmp_path)

    def fake_agent(instruction, workdir, model, timeout_sec, otel):
        (workdir / "hello.txt").write_text("hello")
        return run_engine.AgentRun("done", tokens_in=7, tokens_out=3, tool_calls=1)

    result = run_engine.run_task(
        task,
        settings,
        model="stub-model",
        no_docker=True,
        agent_runner=fake_agent,
    )

    assert result.ok
    assert result.solved
    assert result.tokens_in == 7
    assert result.tokens_out == 3
    assert result.tokens_total == 10
    assert result.tool_calls == 1
    assert result.error is None
    data = json.loads((result.workspace / "result.json").read_text())
    assert data["solved"] is True
    assert data["slug"] == "contest-hello-file"


def test_run_task_unsolved_is_ok_but_not_solved(tmp_path):
    task = _hello_task(tmp_path)
    settings = _settings(tmp_path)

    def fake_agent(instruction, workdir, model, timeout_sec, otel):
        return run_engine.AgentRun("I did nothing", 1, 1, 0)

    result = run_engine.run_task(
        task,
        settings,
        model=None,
        no_docker=True,
        agent_runner=fake_agent,
    )

    assert result.ok
    assert not result.solved
    assert result.error is None
    assert "verifier" not in (result.error or "")
    assert result.score_detail  # pytest output captured


def test_run_task_agent_error(tmp_path):
    task = _hello_task(tmp_path)
    settings = _settings(tmp_path)

    def fake_agent(instruction, workdir, model, timeout_sec, otel):
        raise RuntimeError("boom")

    result = run_engine.run_task(
        task,
        settings,
        model=None,
        no_docker=True,
        agent_runner=fake_agent,
    )

    assert not result.ok
    assert not result.solved
    assert "boom" in (result.error or "")


def test_agent_sees_task_slug_env(tmp_path):
    task = _hello_task(tmp_path)
    settings = _settings(tmp_path)
    seen: dict = {}

    def fake_agent(instruction, workdir, model, timeout_sec, otel):
        seen["slug"] = os.environ.get("SLEPA_TASK_SLUG")
        return run_engine.AgentRun("done", 0, 0, 0)

    run_engine.run_task(
        task, settings, model=None, no_docker=True, agent_runner=fake_agent
    )
    assert seen["slug"] == "contest-hello-file"
    assert "SLEPA_TASK_SLUG" not in os.environ


def test_run_task_missing_instruction(tmp_path):
    task_dir = tmp_path / "tasks" / "broken"
    task_dir.mkdir(parents=True)
    task = Task(slug="broken", name="Broken", path=task_dir)
    settings = _settings(tmp_path)

    result = run_engine.run_task(
        task, settings, model=None, no_docker=True,
        agent_runner=lambda *a: run_engine.AgentRun("", 0, 0, 0),
    )

    assert not result.ok
    assert "instruction.md" in (result.error or "")
