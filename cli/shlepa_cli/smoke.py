"""shlepa smoke: end-to-end dev pipeline check.

Stages (fail-fast; each stage is reported on its own line):

1. doctor — the hard environment checks (LLM endpoint + model, MLflow,
   docker)
2. task   — a dev-engine run of the trivial contest task
   ``contest-hello-file`` (container mode, or the SLEPA_NO_DOCKER host
   path when SLEPA_NO_DOCKER=1); it must finish without error AND be
   solved
3. mlflow — the task result must be logged as a FINISHED MLflow run in
   the 'smoke' experiment (logged even when the task failed, so a red
   run stays diagnosable from the MLflow record)
"""

from __future__ import annotations

import os
from typing import Callable

from shlepa_cli.config import Settings
from shlepa_cli.doctor import CheckResult, run_doctor
from shlepa_cli.run_engine import TaskResult

SMOKE_TASK_SLUG = "contest-hello-file"
SMOKE_EXPERIMENT = "smoke"


def run_smoke(
    settings: Settings,
    *,
    ci: bool = False,
    out: Callable[[str], None] = print,
    doctor_results: list[CheckResult] | None = None,
    task_result: TaskResult | None = None,
    mlflow_client=None,
) -> bool:
    """Run all smoke stages; True only when every stage passes.

    ``ci=True`` switches to the secondary CI endpoint (with fallbacks to
    the main endpoint) and logs the result to the ``shlepa-ci`` experiment
    with ``endpoint_class=ci``.

    ``doctor_results`` / ``task_result`` / ``mlflow_client`` are
    injectable for tests; by default the real doctor, the real
    dev-engine run and the configured MLflow are used.
    """
    import dataclasses

    from shlepa_cli import submit_test

    experiment = SMOKE_EXPERIMENT
    endpoint_class = "main"
    effective = settings
    if ci:
        base_url, api_key, model, endpoint_class, experiment = (
            submit_test.resolve_endpoint(settings, ci=True)
        )
        effective = dataclasses.replace(
            settings,
            openai_base_url=base_url,
            openai_api_key=api_key,
            local_agent_model=model,
        )

    # Stage 1: doctor
    if doctor_results is None:
        doctor_results = run_doctor(effective)[0]
    failed = [c.name for c in doctor_results if not c.ok]
    if failed:
        out(f"doctor: FAIL ({', '.join(failed)})")
        return False
    out("doctor: ok")

    # Stage 2: task
    if task_result is None:
        task_result = _run_smoke_task(effective)
    if task_result is None:
        out(f"task: FAIL (task {SMOKE_TASK_SLUG} not found)")
        return False
    if not task_result.ok:
        out(f"task: FAIL (error: {task_result.error})")
    elif not task_result.solved:
        out(f"task: FAIL (unsolved: {task_result.score_detail})")
    else:
        out(
            f"task: ok ({SMOKE_TASK_SLUG} solved in "
            f"{task_result.duration_sec}s, tokens={task_result.tokens_total})"
        )

    # Stage 3: mlflow — the result is logged even when the task failed,
    # so a red smoke (in particular in CI) leaves a diagnosable run record
    if mlflow_client is None:
        from shlepa_cli.mlflow_client import get_mlflow_client

        mlflow_client = get_mlflow_client(effective)
    from shlepa_cli import run_engine

    try:
        run_id = run_engine.log_task_to_mlflow(
            mlflow_client,
            effective,
            experiment,
            effective.local_agent_model,
            task_result,
            endpoint_class=endpoint_class,
        )
        run = mlflow_client.get_run(run_id)
        if run.info.status != "FINISHED":
            raise RuntimeError(f"run status is {run.info.status}, not FINISHED")
    except Exception as exc:  # noqa: BLE001 - report the stage failure
        out(f"mlflow: FAIL ({type(exc).__name__}: {exc})")
        return False
    out(f"mlflow: ok (experiment={experiment} run={run_id})")
    return bool(task_result.ok and task_result.solved)


def _run_smoke_task(settings: Settings) -> TaskResult | None:
    """Run the smoke task through the dev engine (real docker or host)."""
    from shlepa_cli import run_engine
    from shlepa_cli.tasks import discover_tasks

    try:
        tasks = discover_tasks(settings.repo_root / "tasks")
    except ValueError:
        return None
    task = next((t for t in tasks if t.slug == SMOKE_TASK_SLUG), None)
    if task is None:
        return None
    no_docker = os.environ.get("SLEPA_NO_DOCKER") == "1"
    return run_engine.run_task(
        task,
        settings,
        model=settings.local_agent_model,
        no_docker=no_docker,
    )
