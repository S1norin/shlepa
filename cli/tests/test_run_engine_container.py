"""Run engine tests: container mode (fake docker client)."""

import subprocess
from pathlib import Path

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.docker_client import DockerClient, Mount
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


def _task(root, slug="contest-hello-file", with_env=True):
    task_dir = root / "tasks" / slug
    (task_dir / "tests").mkdir(parents=True)
    if with_env:
        (task_dir / "environment").mkdir()
        (task_dir / "environment" / "Dockerfile").write_text(
            "FROM python:3.12-slim\n"
        )
    (task_dir / "instruction.md").write_text("Create hello.txt")
    (task_dir / "tests" / "test_check.py").write_text("def test_x():\n    pass\n")
    return Task(
        slug=slug,
        name=slug,
        path=task_dir,
        timeout_sec=120,
        env={"APP_PORT": "8080"},
    )


class FakeDocker:
    def __init__(self, exec_rc=0, exec_out="1 passed in 0.01s", build_error=None, has_pytest=True):
        self.exec_rc = exec_rc
        self.exec_out = exec_out
        self.build_error = build_error
        self.has_pytest = has_pytest
        self.pip_installs = 0
        self.built: list[tuple[str, str]] = []
        self.runs: list[dict] = []
        self.execs: list[tuple[str, list[str], dict]] = []
        self.stopped: list[str] = []

    def build(self, image, context):
        if self.build_error:
            raise self.build_error
        self.built.append((image, str(context)))

    def run(self, name, image, mounts, env):
        self.runs.append({"name": name, "image": image, "mounts": mounts, "env": env})
        return f"container-{name}"

    def exec(self, name, cmd, env):
        self.execs.append((name, cmd, env))
        if "--version" in cmd:
            if self.has_pytest:
                return subprocess.CompletedProcess(cmd, 0, stdout="pytest 8.0", stderr="")
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="No module named pytest")
        if "pip" in cmd and "install" in cmd:
            self.pip_installs += 1
            self.has_pytest = True
            return subprocess.CompletedProcess(cmd, 0, stdout="installed", stderr="")
        return subprocess.CompletedProcess(cmd, self.exec_rc, stdout=self.exec_out, stderr="")

    def stop(self, name):
        self.stopped.append(name)


def test_container_mode_solved(tmp_path):
    task = _task(tmp_path)
    fake = FakeDocker(exec_rc=0)
    result = run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        agent_runner=lambda *a: run_engine.AgentRun("done", 4, 2, 1),
        docker_client=fake,
    )

    assert result.ok
    assert result.solved
    # Image built from the task environment directory.
    assert fake.built == [("shlepa-task-contest-hello-file:dev",
                           str(task.environment_dir))]
    # Workspace mounted rw at /workspace, tests mounted ro at /tests.
    run = fake.runs[0]
    assert run["env"] == {"APP_PORT": "8080"}
    assert Mount(result.workspace, "/workspace") in run["mounts"]
    assert Mount(task.path / "tests", "/tests", readonly=True) in run["mounts"]
    # Verifier ran inside the container.
    verifier = [(n, c, e) for n, c, e in fake.execs if c[3] == "/tests"][0]
    name, cmd, env = verifier
    assert name == f"container-{run['name']}"
    assert cmd == [
        "python", "-m", "pytest", "/tests", "-q", "--tb=short",
        "-p", "no:cacheprovider",
    ]
    assert env["SLEPA_WORKSPACE"] == "/workspace"
    assert env["SLEPA_TASK_SLUG"] == "contest-hello-file"
    assert fake.pip_installs == 0  # pytest already present
    # Container cleaned up.
    assert fake.stopped == [f"container-{run['name']}"]


def test_container_mode_unsolved(tmp_path):
    task = _task(tmp_path)
    fake = FakeDocker(exec_rc=1, exec_out="1 failed")
    result = run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        agent_runner=lambda *a: run_engine.AgentRun("done", 0, 0, 0),
        docker_client=fake,
    )
    assert result.ok
    assert not result.solved
    assert result.error is None
    assert "1 failed" in result.score_detail


def test_container_mode_installs_pytest_when_missing(tmp_path):
    task = _task(tmp_path)
    fake = FakeDocker(exec_rc=0, has_pytest=False)
    result = run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        agent_runner=lambda *a: run_engine.AgentRun("done", 0, 0, 0),
        docker_client=fake,
    )
    assert result.ok
    assert result.solved
    assert fake.pip_installs == 1


def test_container_mode_build_error_stops_container(tmp_path):
    task = _task(tmp_path)
    fake = FakeDocker(build_error=RuntimeError("no docker daemon"))
    result = run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        agent_runner=lambda *a: run_engine.AgentRun("done", 0, 0, 0),
        docker_client=fake,
    )
    assert not result.ok
    assert "no docker daemon" in (result.error or "")
    assert fake.stopped == []  # container never started


def test_docker_client_builds_expected_commands(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "run":
            return subprocess.CompletedProcess(cmd, 0, stdout="abc123\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    client = DockerClient()
    ws = Path("/tmp/ws")
    image = "shlepa-task-x:dev"
    client.build(image, "/tmp/task/environment")
    assert calls[0] == ["docker", "build", "-t", image, "/tmp/task/environment"]
    cid = client.run(
        "shlepa-x-1",
        image,
        [Mount(ws, "/workspace"), Mount("/tmp/task/tests", "/tests", readonly=True)],
        {"K": "V"},
    )
    assert cid == "abc123"
    assert calls[1] == [
        "docker", "run", "-d", "--name", "shlepa-x-1",
        "-v", "/tmp/ws:/workspace",
        "-v", "/tmp/task/tests:/tests:ro",
        "-e", "K=V",
        image, "sleep", "infinity",
    ]
    client.exec("shlepa-x-1", ["python", "-m", "pytest", "/tests"], {"A": "B"})
    assert calls[2] == [
        "docker", "exec", "-e", "A=B", "shlepa-x-1",
        "python", "-m", "pytest", "/tests",
    ]
    client.stop("shlepa-x-1")
    assert calls[3] == ["docker", "stop", "-t", "10", "shlepa-x-1"]
