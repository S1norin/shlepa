"""Dev run engine for 'shlepa run [preset]'.

Per task: a workspace under tmp/<YYYYMMDD-HHMMSS>-<slug>/, the agent runs
on the host (imported shlepa_agent core), the verifier is the task's
tests/ (pytest inside the task container, or on the host in
SLEPA_NO_DOCKER mode). Results are written as JSON into the workspace
and logged to MLflow.
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
        "endpoint_class": "main",
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
    """Run the task's tests/ inside the environment container.

    The environment image is not guaranteed to ship pytest; if it is
    missing, install it into the container first (dev machines have
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

    ``agent_runner(instruction, workdir, model, timeout_sec, otel_enabled)
    -> AgentRun`` is injected for testability; the default is
    :func:`run_agent_on_host`. In container mode the agent still runs on
    the host against the workspace; only the verifier (pytest) runs
    inside the task environment container.
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
        from shlepa_cli.docker_client import Mount

        image = f"shlepa-task-{task.slug}:dev"
        try:
            docker_client.build(image, task.environment_dir)
            container = docker_client.run(
                name=f"shlepa-{task.slug}-{time.time_ns() % 10**8}",
                image=image,
                mounts=[
                    Mount(workspace, "/workspace"),
                    Mount(task.path / "tests", "/tests", readonly=True),
                ],
                env=task.env,
            )
            instruction = instruction_file.read_text()
            agent_run = _call_agent(
                agent_runner,
                task,
                instruction,
                workspace,
                model,
                settings,
            )
            solved, score_detail = _score_container(docker_client, container, task)
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
