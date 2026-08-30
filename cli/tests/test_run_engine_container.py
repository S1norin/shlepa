"""Run engine tests: container mode, contest-faithful topology (fake docker).

The agent runs INSIDE the task environment container (acp image + dev
wrapper), the verifier is tests/test.sh writing the host-mounted
/logs/verifier/reward.txt, and the container uses host networking so
telemetry reaches the local OTLP collector.
"""

import json
import re
import subprocess
from pathlib import Path

import shlepa_agent

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.docker_client import Mount
from shlepa_cli.tasks import Preset, Task

BATCH_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


BATCH_ENV_KEYS = (
    "SLEPA_BATCH_ID",
    "SLEPA_PRESET",
    "SLEPA_GIT_SHA",
    "SLEPA_AGENT_VERSION",
)


def _agent_exec_env(fake):
    """Env dict of the in-container agent exec (dev_run.py)."""
    for _name, cmd, env, _timeout in fake.execs:
        if "/agent/dev_run.py" in cmd:
            return env
    raise AssertionError("agent exec not captured")


MARKER = (
    'SLEPA_AGENT_METRICS_JSON='
    '{"final_output": "answer", "tokens_in": 4, "tokens_out": 2, '
    '"tool_calls": 1}\n'
)


def _settings(root, **overrides):
    base = dict(
        repo_root=root,
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model="test-model",
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )
    base.update(overrides)
    return Settings(**base)


def _repo(root: Path, with_test_sh=True):
    (root / "agent" / "shlepa_agent").mkdir(parents=True, exist_ok=True)
    (root / "agent" / "pyproject.toml").write_text(
        "[project]\n"
        'name = "shlepa-agent"\n'
        'requires-python = ">=3.12"\n'
        'dependencies = ["pydantic-ai-slim[openai]", "python-dotenv"]\n'
    )
    (root / "agent" / "shlepa_agent" / "__init__.py").write_text(
        "__version__ = '0.1.0'\n"
    )
    (root / "agent" / "shlepa_agent" / "core.py").write_text("X = 1\n")
    task_dir = root / "tasks" / "contest-hello-file"
    (task_dir / "tests").mkdir(parents=True, exist_ok=True)
    if with_test_sh:
        (task_dir / "tests" / "test.sh").write_text("#!/bin/bash\n")
    (task_dir / "environment").mkdir(parents=True, exist_ok=True)
    (task_dir / "environment" / "Dockerfile").write_text(
        "FROM secureintelligent/acp:latest\nWORKDIR /app\n"
    )
    (task_dir / "instruction.md").write_text("Create hello.txt")
    return Task(
        slug="contest-hello-file",
        name="contest-hello-file",
        path=task_dir,
        timeout_sec=120,
        env={"APP_PORT": "8080"},
    )


class FakeDocker:
    def __init__(
        self,
        reward="1",
        agent_rc=0,
        agent_stderr=MARKER,
        build_error=None,
        cp_error=None,
    ):
        self.reward = reward
        self.agent_rc = agent_rc
        self.agent_stderr = agent_stderr
        self.build_error = build_error
        self.cp_error = cp_error
        self.built: list[tuple[str, str]] = []
        self.runs: list[dict] = []
        self.execs: list[tuple[str, list[str], dict, object]] = []
        self.cps: list[tuple[str, str, str]] = []
        self.stopped: list[str] = []
        self.logs_host_dir: Path | None = None

    def build(self, image, context):
        if self.build_error:
            raise self.build_error
        self.built.append((image, str(context)))

    def run(self, name, image, mounts, env, network=None):
        self.runs.append(
            {
                "name": name,
                "image": image,
                "mounts": list(mounts),
                "env": env,
                "network": network,
            }
        )
        for mount in mounts:
            if mount.target == "/logs/verifier":
                self.logs_host_dir = Path(mount.host)
        return f"container-{name}"

    def exec(self, name, cmd, env, timeout=None):
        self.execs.append((name, list(cmd), dict(env), timeout))
        if "/agent/dev_run.py" in cmd:
            return subprocess.CompletedProcess(
                cmd, self.agent_rc, stdout="answer", stderr=self.agent_stderr
            )
        if cmd[-1] == "/tests/test.sh":
            if self.reward is not None and self.logs_host_dir is not None:
                (self.logs_host_dir / "reward.txt").write_text(self.reward)
            return subprocess.CompletedProcess(cmd, 0, stdout="verifier", stderr="")
        if "pytest" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="1 passed", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    def cp_out(self, name, src, dst):
        if self.cp_error:
            raise self.cp_error
        self.cps.append((name, src, str(dst)))

    def stop(self, name):
        self.stopped.append(name)


class _TimeoutExecDocker(FakeDocker):
    """FakeDocker whose agent exec hits the subprocess hard timeout."""

    def exec(self, name, cmd, env, timeout=None):
        if "/agent/dev_run.py" in cmd:
            raise subprocess.TimeoutExpired(cmd, timeout or 240)
        return super().exec(name, cmd, env, timeout)


def test_container_ok_termination(tmp_path: Path):
    fake = FakeDocker(reward="1")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert result.ok
    assert result.termination == "ok"


def test_container_exec_hard_timeout_reports_exec_timeout(tmp_path: Path):
    fake = _TimeoutExecDocker(reward=None)
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert not result.ok
    assert result.termination == "exec_timeout"
    data = json.loads((result.workspace / "result.json").read_text())
    assert data["termination"] == "exec_timeout"


def test_container_agent_crash_reports_crash(tmp_path: Path):
    fake = FakeDocker(reward=None, agent_rc=1, agent_stderr="Traceback: boom")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert not result.ok
    assert result.termination == "crash"
    data = json.loads((result.workspace / "result.json").read_text())
    assert data["termination"] == "crash"


def test_container_oom_killed_reports_oom(tmp_path: Path):
    fake = FakeDocker(reward=None, agent_rc=137, agent_stderr="Killed")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert not result.ok
    assert result.termination == "oom"
    data = json.loads((result.workspace / "result.json").read_text())
    assert data["termination"] == "oom"


def test_container_faithful_solved(tmp_path: Path):
    fake = FakeDocker(reward="1")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        docker_client=fake,
    )
    assert result.ok
    assert result.solved
    assert result.tokens_in == 4
    assert result.tokens_out == 2
    assert result.tool_calls == 1
    assert result.final_output == "answer"

    # Two images: the task env image and the dev wrapper on top.
    env_image = "shlepa-task-contest-hello-file:env"
    dev_image = "shlepa-task-contest-hello-file:dev"
    assert fake.built[0] == (env_image, str(task.environment_dir))
    dev_context = Path(fake.built[1][1])
    assert fake.built[1][0] == dev_image
    assert dev_context.joinpath("Dockerfile").read_text().startswith(
        f"FROM {env_image}\n"
    )
    assert (dev_context / "dev_agent" / "shlepa_agent" / "core.py").is_file()

    # Host networking; tests ro + host-mounted verifier logs; no /workspace.
    run = fake.runs[0]
    assert run["image"] == dev_image
    assert run["network"] == "host"
    assert run["env"] == {"APP_PORT": "8080"}
    assert Mount(task.path / "tests", "/tests", readonly=True) in run["mounts"]
    logs_mount = [m for m in run["mounts"] if m.target == "/logs/verifier"]
    assert logs_mount and not logs_mount[0].readonly
    assert str(result.workspace) in str(logs_mount[0].host)
    assert not any(m.target == "/workspace" for m in run["mounts"])

    # Agent exec with the contest env: workdir /app, model, timeout.
    agent_exec = [e for e in fake.execs if "/agent/dev_run.py" in e[1]][0]
    name, cmd, env, timeout = agent_exec
    assert name == f"container-{run['name']}"
    assert cmd == [
        "/app/.venv/bin/python",
        "/agent/dev_run.py",
        "Create hello.txt",
    ]
    assert env["LOCAL_AGENT_WORKDIR"] == "/app"
    assert env["LOCAL_AGENT_MODEL"] == "m"
    assert env["SLEPA_AGENT_TIMEOUT"] == "120"
    assert "OPENAI_API_KEY" not in env  # not in settings
    assert timeout == 240

    # Verifier exec + reward read from the host mount.
    verifier_exec = [e for e in fake.execs if e[1][-1] == "/tests/test.sh"][0]
    assert verifier_exec[1] == ["bash", "/tests/test.sh"]
    assert "reward=1" in result.score_detail

    # /app copied back for inspection; container stopped.
    assert fake.cps[0][0] == f"container-{run['name']}"
    assert fake.cps[0][1] == "/app"
    assert fake.stopped == [f"container-{run['name']}"]


def test_dev_dockerfile_covers_no_uv_and_no_venv(tmp_path: Path):
    """Dev Dockerfile must survive env images without uv or /app/.venv."""
    fake = FakeDocker(reward="1")
    task = _repo(tmp_path)
    run_engine.run_task(
        task,
        _settings(tmp_path),
        model="m",
        no_docker=False,
        docker_client=fake,
    )
    dev_context = Path(fake.built[1][1])
    text = (dev_context / "Dockerfile").read_text()
    # uv detection: PATH first, then the acp venv location, then a
    # bootstrap of the pinned static release when neither exists.
    assert "command -v uv" in text
    assert "/app/.venv/bin/uv" in text
    assert "astral-sh/uv/releases" in text
    # Images without /app/.venv get a fresh agent venv with the agent's
    # own dependencies (extras shell-quoted) before the telemetry pin.
    assert "venv /app/.venv --python 3.12" in text
    assert "'pydantic-ai-slim[openai]'" in text
    # The telemetry pin is installed on every path.
    assert "openinference-instrumentation-pydantic-ai" in text


def test_container_faithful_unsolved(tmp_path: Path):
    fake = FakeDocker(reward="0")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert result.ok
    assert result.solved is False
    assert result.error is None
    assert "reward=0" in result.score_detail


def test_container_faithful_agent_crash(tmp_path: Path):
    fake = FakeDocker(agent_rc=1, agent_stderr="Traceback: boom")
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert result.ok is False
    assert "exited with code 1" in (result.error or "")
    assert "boom" in (result.error or "")
    # Verifier never runs after an agent crash.
    assert not any(e[1][-1] == "/tests/test.sh" for e in fake.execs)


def test_container_faithful_build_error(tmp_path: Path):
    fake = FakeDocker(build_error=RuntimeError("no docker daemon"))
    task = _repo(tmp_path)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert result.ok is False
    assert "no docker daemon" in (result.error or "")
    assert fake.stopped == []


def test_container_faithful_no_test_sh_falls_back_to_pytest(tmp_path: Path):
    fake = FakeDocker()
    task = _repo(tmp_path, with_test_sh=False)
    result = run_engine.run_task(
        task, _settings(tmp_path), model="m", no_docker=False, docker_client=fake
    )
    assert result.ok
    assert result.solved  # fake pytest answers rc=0
    assert not any(e[1][-1] == "/tests/test.sh" for e in fake.execs)


def test_run_preset_batch_env_when_otel_enabled(tmp_path: Path):
    fake = FakeDocker()
    task = _repo(tmp_path)
    settings = _settings(
        tmp_path,
        shlepa_otel_enabled=True,
        otel_exporter_otlp_endpoint="http://localhost:4318",
    )
    run_engine.run_preset(
        settings,
        Preset(name="all", tasks="all"),
        [task],
        model="m",
        no_docker=False,
        docker_client=fake,
        batch_id="20260827-233000-abcdef",
    )
    env = _agent_exec_env(fake)
    assert env["SLEPA_BATCH_ID"] == "20260827-233000-abcdef"
    assert env["SLEPA_PRESET"] == "all"
    assert env["SLEPA_AGENT_VERSION"] == shlepa_agent.__version__
    # The tmp repo is not a git checkout; the engine reports 'unknown'.
    assert env["SLEPA_GIT_SHA"] == "unknown"


def test_run_preset_no_batch_env_when_otel_disabled(tmp_path: Path):
    fake = FakeDocker()
    task = _repo(tmp_path)
    run_engine.run_preset(
        _settings(tmp_path),
        Preset(name="all", tasks="all"),
        [task],
        model="m",
        no_docker=False,
        docker_client=fake,
    )
    env = _agent_exec_env(fake)
    for key in BATCH_ENV_KEYS:
        assert key not in env


def test_run_preset_generates_batch_id_per_invocation(tmp_path: Path):
    settings = _settings(tmp_path, shlepa_otel_enabled=True)
    preset = Preset(name="all", tasks="all")
    ids = []
    for _ in range(2):
        fake = FakeDocker()
        task = _repo(tmp_path)
        run_engine.run_preset(
            settings,
            preset,
            [task],
            model="m",
            no_docker=False,
            docker_client=fake,
        )
        ids.append(_agent_exec_env(fake)["SLEPA_BATCH_ID"])
    assert len(set(ids)) == 2
    for batch_id in ids:
        assert BATCH_ID_RE.match(batch_id)


def test_run_preset_warns_when_collector_unreachable(
    tmp_path: Path, monkeypatch, capsys
):
    fake = FakeDocker()
    task = _repo(tmp_path)
    settings = _settings(tmp_path, shlepa_otel_enabled=True)
    probed = []

    def _down(endpoint):
        probed.append(endpoint)
        return False

    monkeypatch.setattr(run_engine, "_probe_collector", _down)
    run_engine.run_preset(
        settings,
        Preset(name="all", tasks="all"),
        [task],
        model="m",
        no_docker=False,
        docker_client=fake,
    )
    assert probed == ["http://localhost:4318"]
    err = capsys.readouterr().err
    assert "collector unreachable" in err
    assert "traces will be LOST" in err


def test_probe_collector_never_raises(monkeypatch):
    # the health port is fixed at 13133 per otel/otelcol.yaml; any probe
    # failure (refused, timeout, DNS) must yield False, never raise
    def _refused(*args, **kwargs):
        raise OSError("connection refused")

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _refused)
    assert run_engine._probe_collector("http://127.0.0.1:4318") is False


def test_run_preset_no_probe_when_otel_disabled(
    tmp_path: Path, monkeypatch, capsys
):
    fake = FakeDocker()
    task = _repo(tmp_path)
    settings = _settings(tmp_path)

    def _no_probe(endpoint):
        raise AssertionError("probe must not run")

    monkeypatch.setattr(run_engine, "_probe_collector", _no_probe)
    run_engine.run_preset(
        settings,
        Preset(name="all", tasks="all"),
        [task],
        model="m",
        no_docker=False,
        docker_client=fake,
    )
    assert "collector unreachable" not in capsys.readouterr().err


def test_container_faithful_agent_env_from_settings(tmp_path: Path):
    fake = FakeDocker()
    task = _repo(tmp_path)
    settings = _settings(
        tmp_path,
        openai_base_url="http://llm.example/v1",
        openai_api_key="sk-test",
        shlepa_otel_enabled=True,
        otel_exporter_otlp_endpoint="http://localhost:4318",
    )
    run_engine.run_task(
        task, settings, model=None, no_docker=False, docker_client=fake
    )
    agent_exec = [e for e in fake.execs if "/agent/dev_run.py" in e[1]][0]
    env = agent_exec[2]
    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["OPENAI_BASE_URL"] == "http://llm.example/v1"
    assert env["LOCAL_AGENT_MODEL"] == "test-model"
    assert env["SLEPA_OTEL_ENABLED"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://localhost:4318"
