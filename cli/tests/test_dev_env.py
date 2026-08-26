"""Tests for the in-container dev agent environment (dev_env)."""

from pathlib import Path

from shlepa_cli import dev_env


def _make_agent_repo(base: Path) -> Path:
    agent = base / "agent"
    (agent / "shlepa_agent" / "telemetry").mkdir(parents=True)
    (agent / "tests").mkdir()
    (agent / "run.sh").write_text("#!/bin/bash\n")
    (agent / "agent.py").write_text("print('agent')\n")
    (agent / "pyproject.toml").write_text("[project]\n")
    (agent / "shlepa_agent" / "__init__.py").write_text("__version__ = '0.1.0'\n")
    (agent / "shlepa_agent" / "__main__.py").write_text("M = 1\n")
    (agent / "shlepa_agent" / "core.py").write_text("X = 1\n")
    (agent / "shlepa_agent" / "telemetry" / "__init__.py").write_text("T = 1\n")
    (agent / "tests" / "test_x.py").write_text("")
    return agent


def test_stage_agent_copies_only_the_package(tmp_path: Path) -> None:
    agent = _make_agent_repo(tmp_path)
    context = tmp_path / "ctx"

    dev_env.stage_agent(context, agent)

    assert (context / "dev_agent" / "shlepa_agent" / "core.py").is_file()
    # Telemetry ships into the dev image (local only, never zipped).
    assert (
        context / "dev_agent" / "shlepa_agent" / "telemetry" / "__init__.py"
    ).is_file()
    assert (context / "dev_agent" / "dev_run.py").is_file()
    # Submission-only files are not part of the dev agent dir.
    assert not (context / "dev_agent" / "run.sh").exists()
    assert not (context / "dev_agent" / "agent.py").exists()
    assert not (context / "dev_agent" / "tests").exists()
    assert not (context / "dev_agent" / "pyproject.toml").exists()


def test_stage_agent_ignores_pycache(tmp_path: Path) -> None:
    agent = _make_agent_repo(tmp_path)
    pycache = agent / "shlepa_agent" / "__pycache__"
    pycache.mkdir()
    (pycache / "core.cpython-312.pyc").write_bytes(b"\x00")

    dev_env.stage_agent(tmp_path / "ctx", agent)

    assert not (tmp_path / "ctx" / "dev_agent" / "shlepa_agent" / "__pycache__").exists()


def test_write_dev_dockerfile(tmp_path: Path) -> None:
    dev_env.write_dev_dockerfile(tmp_path, "shlepa-task-hello-file:env")
    text = (tmp_path / "Dockerfile").read_text()
    assert text.startswith("FROM shlepa-task-hello-file:env\n")
    assert "COPY dev_agent/ /agent/" in text
    # Build-time only: telemetry enrichment package is installed into the
    # acp venv (which already has pydantic-ai + the OTel SDK).
    assert "/app/.venv/bin/uv pip install" in text
    assert "openinference-instrumentation-pydantic-ai" in text


def test_build_dev_image_builds_on_top_of_env_image(tmp_path: Path) -> None:
    class FakeDocker:
        def __init__(self) -> None:
            self.built = []

        def build(self, image: str, context: Path) -> None:
            self.built.append((image, context))

    agent = _make_agent_repo(tmp_path)
    docker = FakeDocker()

    image = dev_env.build_dev_image(
        docker,
        env_image="shlepa-task-hello-file:env",
        dev_image="shlepa-task-hello-file:dev",
        agent_dir=agent,
        workdir=tmp_path / "ws",
    )

    assert image == "shlepa-task-hello-file:dev"
    assert len(docker.built) == 1
    built_image, context = docker.built[0]
    assert built_image == "shlepa-task-hello-file:dev"
    assert (context / "Dockerfile").is_file()
    assert (context / "dev_agent" / "shlepa_agent" / "core.py").is_file()


def test_parse_agent_metrics() -> None:
    stderr = (
        "log line\n"
        'SLEPA_AGENT_METRICS_JSON={"final_output": "hello", '
        '"tokens_in": 5, "tokens_out": 7, "tool_calls": 2}\n'
        "trailing\n"
    )
    assert dev_env.parse_agent_metrics(stderr) == {
        "final_output": "hello",
        "tokens_in": 5,
        "tokens_out": 7,
        "tool_calls": 2,
    }


def test_parse_agent_metrics_missing_or_broken() -> None:
    defaults = {
        "final_output": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "tool_calls": 0,
    }
    assert dev_env.parse_agent_metrics("no marker") == defaults
    assert dev_env.parse_agent_metrics("") == defaults
    assert dev_env.parse_agent_metrics("SLEPA_AGENT_METRICS_JSON={broken") == defaults


def test_dev_run_source_sanity() -> None:
    # The generated entrypoint must be valid python and carry the marker.
    compile(dev_env.DEV_RUN_SOURCE, "dev_run.py", "exec")
    assert dev_env.METRICS_MARKER in dev_env.DEV_RUN_SOURCE
    assert '"/agent"' in dev_env.DEV_RUN_SOURCE
