"""Run engine tests: host agent execution + scoring (s2)."""

from stream_stub import FINAL_ANSWER, start_stream_stub

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
    return Task(slug=slug, name="Hello File", path=task_dir, timeout_sec=120)


def test_run_agent_on_host_against_stub(monkeypatch, tmp_path):
    server, url = start_stream_stub()
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    try:
        run = run_engine.run_agent_on_host(
            "Create hello.txt", tmp_path, "stub-model", 60, False
        )
    finally:
        server.shutdown()
        server.server_close()

    assert run.final_output == FINAL_ANSWER
    assert run.tokens_in == 10
    assert run.tokens_out == 5
    assert run.tool_calls == 0


def test_run_task_end_to_end_stub_llm(monkeypatch, tmp_path):
    """Full no-docker loop: real agent on the host, pytest verifier."""
    server, url = start_stream_stub()
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    try:
        task = _hello_task(tmp_path)
        settings = _settings(tmp_path)
        # The stub LLM never calls tools, so the file is not created and
        # the task must come out unsolved but ok.
        result = run_engine.run_task(
            task,
            settings,
            model="stub-model",
            no_docker=True,
            agent_runner=None,  # real host runner
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result.ok
    assert not result.solved
    assert result.final_output == FINAL_ANSWER
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.error is None


def test_run_agent_on_host_timeout(monkeypatch, tmp_path):
    server, url = start_stream_stub()
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    try:
        import pytest

        with pytest.raises(TimeoutError):
            run_engine.run_agent_on_host(
                "hang", tmp_path, "stub-model", 0.001, False
            )
    finally:
        server.shutdown()
        server.server_close()
