"""Dev run engine for 'shlepa run [preset]'.

Container mode (the contest-faithful default): the agent runs INSIDE the
task environment container (built FROM secureintelligent/acp, with a dev
wrapper baking in the shlepa_agent package), working in /app under host
networking; the verifier is the task's tests/test.sh writing the
host-mounted /logs/verifier/reward.txt. SLEPA_NO_DOCKER mode keeps the
experimental host path (agent imported on the host, pytest on the host).
Per task: a workspace under tmp/<YYYYMMDD-HHMMSS>-<slug>/ holding the
verifier logs, the copied-back /app, and result.json; results are also
logged to MLflow.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from shlepa_cli.config import Settings
from shlepa_cli.tasks import Task


@dataclass(frozen=True)
class AgentRun:
    """Outcome of one agent execution."""

    final_output: str
    tokens_in: int
    tokens_out: int
    tool_calls: int


@dataclass(frozen=True)
class TaskResult:
    """Outcome of one task run.

    ``ok`` is False only on hard errors (agent crash, missing files);
    an unsolved task still has ok=True and solved=False.
    """

    slug: str
    ok: bool
    solved: bool
    duration_sec: float
    tokens_in: int
    tokens_out: int
    tokens_total: int
    tool_calls: int
    final_output: str
    error: str | None
    score_detail: str
    workspace: Path


def make_workspace(repo_root: Path, slug: str) -> Path:
    """Create tmp/<YYYYMMDD-HHMMSS>-<slug>/ under the repo root."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = Path(repo_root) / "tmp" / f"{timestamp}-{slug}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def run_agent_on_host(
    instruction: str,
    workdir: Path,
    model: str | None,
    timeout_sec: int | None,
    otel_enabled: bool,
) -> AgentRun:
    """Run the shlepa agent on the host against one instruction.

    Env vars for the agent come from the process environment (the CLI
    loads .env at startup); LOCAL_AGENT_MODEL is overridden by ``model``.
    """
    from shlepa_agent.core import LocalAgentDeps, get_pydantic_agent

    old_model = os.environ.get("LOCAL_AGENT_MODEL")
    if model:
        os.environ["LOCAL_AGENT_MODEL"] = model
    try:
        agent = get_pydantic_agent(instrument=otel_enabled)
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    agent.run(
                        instruction,
                        deps=LocalAgentDeps(workdir=Path(workdir)),
                    ),
                    timeout=timeout_sec,
                )
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"agent timed out after {timeout_sec}s"
            ) from None
    finally:
        if old_model is None:
            os.environ.pop("LOCAL_AGENT_MODEL", None)
        else:
            os.environ["LOCAL_AGENT_MODEL"] = old_model

    usage = result.usage
    return AgentRun(
        final_output=str(result.output),
        tokens_in=int(usage.input_tokens or 0) if usage else 0,
        tokens_out=int(usage.output_tokens or 0) if usage else 0,
        tool_calls=int(usage.tool_calls or 0) if usage else 0,
    )


def _git_sha(repo_root: Path) -> str:
    """Short git HEAD sha of the repo root, or 'unknown'."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "unknown"


def log_task_to_mlflow(
    client,
    settings: Settings,
    preset_name: str,
    model: str | None,
    result: TaskResult,
    endpoint_class: str = "main",
) -> str:
    """Log one task result as an MLflow run; returns the run id.

    experiment = preset name, run name = task slug.
    """
    import shlepa_agent

    experiment = client.get_experiment_by_name(preset_name)
    if experiment is None:
        experiment_id = client.create_experiment(preset_name)
    else:
        experiment_id = experiment.experiment_id
    tags = {
        "preset": preset_name,
        "model": model or "env",
        "agent_version": shlepa_agent.__version__,
        "git_sha": _git_sha(settings.repo_root),
        "endpoint_class": endpoint_class,
    }
    if settings.shlepa_otel_enabled:
        jaeger = (settings.otel_exporter_otlp_endpoint or "http://localhost:4318").replace(
            ":4318", ":16686"
        )
        tags["trace_ref"] = f"{jaeger} service=shlepa-agent task={result.slug}"
    run = client.create_run(
        experiment_id=experiment_id, run_name=result.slug, tags=tags
    )
    run_id = run.info.run_id
    client.log_metric(run_id, "solved", 1.0 if result.solved else 0.0)
    client.log_metric(run_id, "duration_sec", result.duration_sec)
    client.log_metric(run_id, "tokens_in", result.tokens_in)
    client.log_metric(run_id, "tokens_out", result.tokens_out)
    client.log_metric(run_id, "tokens_total", result.tokens_total)
    client.log_metric(run_id, "tool_calls", result.tool_calls)
    client.log_param(run_id, "final_output", result.final_output[:2000])
    if result.error:
        client.log_param(run_id, "error", result.error[:2000])
    result_json = result.workspace / "result.json"
    if result_json.is_file():
        client.log_artifact(run_id, str(result_json), artifact_path="data")
    client.set_terminated(run_id, status="FINISHED")
    return run_id


def _score_no_docker(task: Task, workspace: Path) -> tuple[bool, str]:
    """Run the task's tests/ with pytest on the host (SLEPA_NO_DOCKER mode)."""
    tests_dir = task.path / "tests"
    if not tests_dir.is_dir():
        return False, "no tests/ directory in task"
    env = {
        **os.environ,
        "SLEPA_WORKSPACE": str(workspace),
        "SLEPA_TASK_SLUG": task.slug,
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(tests_dir),
            "-q",
            "--tb=short",
            "-p",
            "no:cacheprovider",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:]


def run_preset(
    settings: Settings,
    preset,
    tasks: list[Task],
    *,
    model: str | None,
    no_docker: bool = True,
    agent_runner=None,
    docker_client=None,
    mlflow_client=None,
) -> list[TaskResult]:
    """Run every task of a preset; a failing task never stops the batch.

    Each task result is logged to MLflow when ``mlflow_client`` is given.
    """
    results: list[TaskResult] = []
    for index, task in enumerate(tasks, 1):
        print(f"[{index}/{len(tasks)}] {task.slug}", flush=True)
        result = run_task(
            task,
            settings,
            model=model,
            no_docker=no_docker,
            agent_runner=agent_runner,
            docker_client=docker_client,
        )
        results.append(result)
        if mlflow_client is not None:
            log_task_to_mlflow(mlflow_client, settings, preset.name, model, result)
        print(
            f"  -> {result.slug}: solved={result.solved} "
            f"duration={result.duration_sec}s tokens={result.tokens_total}"
            + (f" error={result.error}" if result.error else ""),
            flush=True,
        )
    return results


def format_summary(results: list[TaskResult]) -> str:
    """Final summary table for a preset run."""
    if not results:
        return "no tasks run"
    lines = [
        f"{'SLUG':<40} {'STATUS':<7} {'SOLVED':<8} {'DUR(s)':>8} {'TOKENS':>8}  NOTE"
    ]
    for r in results:
        status = "OK" if r.ok else "ERROR"
        note = r.error[:50] if r.error else ("unsolved" if not r.solved else "")
        lines.append(
            f"{r.slug:<40} {status:<7} {str(r.solved).lower():<8} "
            f"{r.duration_sec:>8.1f} {r.tokens_total:>8}  {note}"
        )
    solved = sum(1 for r in results if r.solved)
    lines.append(f"\n{solved}/{len(results)} solved")
    return "\n".join(lines)


def _write_result_json(workspace: Path, result: TaskResult) -> None:
    (workspace / "result.json").write_text(
        json.dumps(asdict(result), indent=2, default=str)
    )


def _call_agent(
    agent_runner,
    task: Task,
    instruction: str,
    workspace: Path,
    model: str | None,
    settings: Settings,
) -> AgentRun:
    """Invoke the agent with SLEPA_TASK_SLUG set for the duration of the run."""
    old_slug = os.environ.get("SLEPA_TASK_SLUG")
    os.environ["SLEPA_TASK_SLUG"] = task.slug
    try:
        return agent_runner(
            instruction,
            workspace,
            model,
            task.timeout_sec,
            settings.shlepa_otel_enabled,
        )
    finally:
        if old_slug is None:
            os.environ.pop("SLEPA_TASK_SLUG", None)
        else:
            os.environ["SLEPA_TASK_SLUG"] = old_slug


def _score_container(docker, container: str, task: Task) -> tuple[bool, str]:
    """Fallback scoring: run the task's tests/ with pytest in the container.

    Used only when the task has no tests/test.sh (non-contest or legacy
    tasks). The environment image is not guaranteed to ship pytest; if it
    is missing, install it into the container first (dev machines have
    network access).
    """
    tests_dir = task.path / "tests"
    if not tests_dir.is_dir():
        return False, "no tests/ directory in task"
    probe = docker.exec(container, ["python", "-m", "pytest", "--version"], {})
    if probe.returncode != 0:
        install = docker.exec(
            container, ["python", "-m", "pip", "install", "--quiet", "pytest"], {}
        )
        if install.returncode != 0:
            detail = (install.stdout or install.stderr)[-1000:]
            return False, f"pytest unavailable in container and install failed: {detail}"
    proc = docker.exec(
        container,
        ["python", "-m", "pytest", "/tests", "-q", "--tb=short", "-p", "no:cacheprovider"],
        {"SLEPA_WORKSPACE": "/workspace", "SLEPA_TASK_SLUG": task.slug},
    )
    return proc.returncode == 0, (proc.stdout or proc.stderr)[-2000:]


def _score_container_faithful(
    docker, container: str, task: Task, reward_file: Path
) -> tuple[bool, str]:
    """Run the contest verifier (tests/test.sh) inside the container.

    The verifier writes 1/0 to /logs/verifier/reward.txt; that path is
    host-mounted, so the reward is read straight from the host after the
    exec finishes.
    """
    test_sh = task.path / "tests" / "test.sh"
    if not test_sh.is_file():
        return False, "no tests/test.sh in task"
    timeout = task.verifier_timeout_sec or 300
    proc = docker.exec(
        container,
        ["bash", "/tests/test.sh"],
        dict(task.verifier_env),
        timeout=timeout,
    )
    if not reward_file.is_file():
        tail = (proc.stdout or proc.stderr)[-1000:]
        return (
            False,
            f"verifier wrote no reward.txt (rc={proc.returncode}): {tail}",
        )
    content = reward_file.read_text().strip()
    detail = (
        f"reward={content or 'empty'} rc={proc.returncode} "
        f"out={(proc.stdout or proc.stderr)[-500:]}"
    )
    return content == "1", detail


def _agent_env(settings: Settings, model: str | None, task: Task) -> dict[str, str]:
    """docker-exec environment for the in-container agent."""
    env: dict[str, str] = {
        "LOCAL_AGENT_WORKDIR": "/app",
        "LOCAL_AGENT_MODEL": model or settings.local_agent_model or "",
        "SLEPA_TASK_SLUG": task.slug,
    }
    if settings.openai_api_key:
        env["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.openai_base_url:
        env["OPENAI_BASE_URL"] = settings.openai_base_url
    if task.timeout_sec:
        env["SLEPA_AGENT_TIMEOUT"] = str(int(task.timeout_sec))
    if settings.shlepa_otel_enabled:
        env["SLEPA_OTEL_ENABLED"] = "1"
        env["OTEL_EXPORTER_OTLP_ENDPOINT"] = (
            settings.otel_exporter_otlp_endpoint or "http://localhost:4318"
        )
    return env


def run_task(
    task: Task,
    settings: Settings,
    *,
    model: str | None,
    no_docker: bool = True,
    agent_runner=None,
    docker_client=None,
) -> TaskResult:
    """Run one task and return its TaskResult.

    Container mode (the contest-faithful default): the agent runs INSIDE
    the task environment container (acp image + dev wrapper with the
    shlepa_agent package baked in, host networking), working in /app;
    the verifier is the task's tests/test.sh writing the host-mounted
    /logs/verifier/reward.txt. ``agent_runner`` is only used by the
    experimental SLEPA_NO_DOCKER host path (see :func:`run_agent_on_host`).
    """
    if agent_runner is None:
        agent_runner = run_agent_on_host
    if docker_client is None and not no_docker:
        from shlepa_cli.docker_client import DockerClient

        docker_client = DockerClient()

    workspace = make_workspace(settings.repo_root, task.slug)
    instruction_file = task.path / "instruction.md"
    started = time.monotonic()
    agent_run = AgentRun("", 0, 0, 0)
    solved = False
    score_detail = ""
    error: str | None = None
    container: str | None = None

    if not instruction_file.is_file():
        error = f"no instruction.md in {task.path}"
    elif no_docker:
        try:
            instruction = instruction_file.read_text()
            agent_run = _call_agent(
                agent_runner,
                task,
                instruction,
                workspace,
                model,
                settings,
            )
            solved, score_detail = _score_no_docker(task, workspace)
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            error = f"{type(exc).__name__}: {exc}"
    else:
        from shlepa_cli import dev_env
        from shlepa_cli.docker_client import Mount

        env_image = f"shlepa-task-{task.slug}:env"
        dev_image = f"shlepa-task-{task.slug}:dev"
        logs_dir = workspace / "logs" / "verifier"
        try:
            docker_client.build(env_image, task.environment_dir)
            dev_env.build_dev_image(
                docker_client,
                env_image=env_image,
                dev_image=dev_image,
                agent_dir=settings.repo_root / "agent",
                workdir=workspace,
            )
            logs_dir.mkdir(parents=True, exist_ok=True)
            container = docker_client.run(
                name=f"shlepa-{task.slug}-{time.time_ns() % 10**8}",
                image=dev_image,
                network="host",
                mounts=[
                    Mount(task.path / "tests", "/tests", readonly=True),
                    Mount(logs_dir, "/logs/verifier"),
                ],
                env=task.env,
            )
            instruction = instruction_file.read_text()
            agent_run = dev_env.run_agent_in_container(
                docker_client,
                container,
                instruction,
                _agent_env(settings, model, task),
                timeout_sec=task.timeout_sec,
            )
            if (task.path / "tests" / "test.sh").is_file():
                solved, score_detail = _score_container_faithful(
                    docker_client, container, task, logs_dir / "reward.txt"
                )
            else:
                solved, score_detail = _score_container(
                    docker_client, container, task
                )
            try:
                docker_client.cp_out(container, "/app", workspace / "app")
            except Exception:  # noqa: BLE001 - debug aid, not fatal
                pass
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if container is not None:
                try:
                    docker_client.stop(container)
                except Exception:  # noqa: BLE001 - best effort cleanup
                    pass

    duration = time.monotonic() - started
    result = TaskResult(
        slug=task.slug,
        ok=error is None,
        solved=solved,
        duration_sec=round(duration, 2),
        tokens_in=agent_run.tokens_in,
        tokens_out=agent_run.tokens_out,
        tokens_total=agent_run.tokens_in + agent_run.tokens_out,
        tool_calls=agent_run.tool_calls,
        final_output=agent_run.final_output,
        error=error,
        score_detail=score_detail,
        workspace=workspace,
    )
    _write_result_json(workspace, result)
    return result
