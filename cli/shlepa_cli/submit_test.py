"""shlepa submit-test: strict contest-faithful test via Harbor.

Builds the submission zip (telemetry stripped), unzips it, and runs
Harbor (harbor==0.16.1, already a cli dependency) against the selected
tasks using the unzipped agent. The agent executes inside the acp
container exactly as in the contest; telemetry is off by construction
because the telemetry package is absent from the zip.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable


#: Import path of the agent class inside the unzipped submission.
AGENT_IMPORT_PATH = "agent:MyInstalledAgent"


class UnzipError(RuntimeError):
    """Raised when a submission archive cannot be unzipped safely."""


@dataclass(frozen=True)
class HarborTrial:
    """One parsed Harbor trial."""

    task_name: str
    status: str  # "solved" | "unsolved" | "timeout" | "error"
    reward: float | None
    tokens_in: int | None
    tokens_out: int | None
    duration_sec: float | None
    error: str | None


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class JobDirNotFound(FileNotFoundError):
    """Raised when the Harbor job directory cannot be located."""


def _trial_from_dict(raw: dict) -> HarborTrial:
    """Convert one Harbor trial dict (TrialResult shape) to HarborTrial.

    A trial is *solved* when its verifier reward equals 1 and no exception
    was raised. A raised exception maps to ``timeout`` (when the exception
    type is a timeout) or ``error`` otherwise.
    """
    exception = raw.get("exception_info")
    error: str | None = None
    status: str | None = None
    if exception is not None:
        etype = exception.get("exception_type", "Exception")
        emsg = exception.get("exception_message", "")
        error = f"{etype}: {emsg}"
        status = "timeout" if "Timeout" in etype else "error"

    verifier = raw.get("verifier_result") or {}
    rewards = verifier.get("rewards")
    reward: float | None = None
    if isinstance(rewards, dict):
        value = rewards.get("reward")
        reward = float(value) if isinstance(value, (int, float)) else None

    if status is None:
        status = "solved" if reward == 1 else "unsolved"

    agent_result = raw.get("agent_result") or {}
    started = _parse_ts(raw.get("started_at"))
    finished = _parse_ts(raw.get("finished_at"))
    duration: float | None = None
    if started is not None and finished is not None:
        duration = (finished - started).total_seconds()

    return HarborTrial(
        task_name=raw.get("task_name") or raw.get("trial_name", ""),
        status=status,
        reward=reward,
        tokens_in=agent_result.get("n_input_tokens"),
        tokens_out=agent_result.get("n_output_tokens"),
        duration_sec=duration,
        error=error,
    )


def parse_job_result(path: Path) -> list[HarborTrial]:
    """Parse a job-level Harbor ``result.json`` (with embedded trials)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Harbor result not found: {path}")
    data = json.loads(path.read_text())
    return [_trial_from_dict(raw) for raw in data.get("trial_results", [])]


def find_job_dir(jobs_dir: Path, job_name: str) -> Path:
    """Locate the Harbor job directory under ``jobs_dir``.

    Prefers ``jobs_dir/job_name``; falls back to the single job directory
    present when the name differs. Raises JobDirNotFound otherwise.
    """
    jobs_dir = Path(jobs_dir)
    exact = jobs_dir / job_name
    if exact.is_dir():
        return exact
    candidates = [
        p for p in jobs_dir.iterdir()
        if p.is_dir() and (p / "result.json").is_file()
    ] if jobs_dir.is_dir() else []
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise JobDirNotFound(
            f"multiple job directories in {jobs_dir}; "
            f"expected job name {job_name!r}"
        )
    raise JobDirNotFound(f"job directory not found: {exact}")


def parse_job_dir(job_dir: Path) -> list[HarborTrial]:
    """Parse all trials of a Harbor job directory.

    Prefers embedded ``trial_results`` in the job-level ``result.json``
    (older Harbor formats); otherwise reads each trial subdirectory's
    ``result.json`` (current Harbor: one file per trial, none embedded).
    """
    job_dir = Path(job_dir)
    job_result = job_dir / "result.json"
    if job_result.is_file():
        data = json.loads(job_result.read_text())
        embedded = data.get("trial_results") or []
        if embedded:
            return [_trial_from_dict(raw) for raw in embedded]
    trials: list[HarborTrial] = []
    if job_dir.is_dir():
        for trial_dir in sorted(job_dir.iterdir()):
            trial_result = trial_dir / "result.json"
            if trial_dir.is_dir() and trial_result.is_file():
                trials.append(
                    _trial_from_dict(json.loads(trial_result.read_text()))
                )
    return trials


def unzip_submission(zip_path: Path, dest_dir: Path) -> Path:
    """Unzip a flat-layout submission archive into ``dest_dir``.

    Rejects path-traversal entries and archives without ``agent.py``.
    Restores the executable bit on ``run.sh``.
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    if not zip_path.is_file():
        raise UnzipError(f"submission zip not found: {zip_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest_dir / member.filename).resolve()
            if not target.is_relative_to(dest_dir.resolve()):
                raise UnzipError(
                    f"unsafe path in zip: {member.filename}"
                )
        zf.extractall(dest_dir)

    agent_py = dest_dir / "agent.py"
    if not agent_py.is_file():
        raise UnzipError(f"agent.py missing from unzipped archive: {dest_dir}")
    run_sh = dest_dir / "run.sh"
    if run_sh.is_file():
        mode = stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH
        os.chmod(run_sh, mode)
    return dest_dir


def harbor_exe() -> Path:
    """Path to the ``harbor`` console script next to the current python."""
    return Path(sys.executable).parent / "harbor"


def build_harbor_command(
    *,
    agent_dir: Path,
    task_path: Path,
    model: str,
    jobs_dir: Path,
    job_name: str,
    base_url: str | None = None,
    api_key: str | None = None,
    harbor_exe_path: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Build the ``harbor job start`` argv and env for one task.

    The unzipped submission lives in ``agent_dir``; Harbor imports the
    agent wrapper via ``PYTHONPATH`` so ``agent:MyInstalledAgent`` resolves
    to the submission's ``agent.py``. Endpoint credentials are forwarded to
    the in-container agent through ``--ae`` (agent env), mirroring the
    contest runtime.
    """
    exe = str(harbor_exe_path or harbor_exe())
    argv = [
        exe,
        "job",
        "start",
        "--agent",
        AGENT_IMPORT_PATH,
        "-m",
        model,
        "--env",
        "docker",
        "--path",
        str(task_path),
        "--jobs-dir",
        str(jobs_dir),
        "--job-name",
        job_name,
        "--n-concurrent",
        "1",
        "--yes",
    ]
    if base_url:
        argv += ["--ae", f"OPENAI_BASE_URL={base_url}"]
    if api_key:
        argv += ["--ae", f"OPENAI_API_KEY={api_key}"]

    env = {"PYTHONPATH": str(agent_dir)}
    existing = os.environ.get("PYTHONPATH")
    if existing:
        env["PYTHONPATH"] = os.pathsep.join([str(agent_dir), existing])
    return argv, env


def _git_short_sha(repo_root: Path) -> str:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


def resolve_endpoint(settings, ci: bool = False):
    """Resolve (base_url, api_key, model, endpoint_class, experiment).

    ``ci=True`` selects the secondary CI endpoint and the ``shlepa-ci``
    experiment; the CI model falls back to the main model when unset.
    """
    if ci:
        base_url = settings.ci_openai_base_url or settings.openai_base_url
        api_key = settings.ci_openai_api_key or settings.openai_api_key
        model = settings.ci_model or settings.local_agent_model
        endpoint_class = "ci"
        experiment = "shlepa-ci"
    else:
        base_url = settings.openai_base_url
        api_key = settings.openai_api_key
        model = settings.local_agent_model
        endpoint_class = "main"
        experiment = "submit-test"
    return base_url, api_key, model, endpoint_class, experiment


def log_trials_to_mlflow(
    client,
    settings,
    *,
    experiment: str,
    model: str | None,
    endpoint_class: str,
    trials: list[HarborTrial],
) -> dict[str, str]:
    """Log parsed Harbor trials as MLflow runs; returns {task_name: run_id}."""
    exp = client.get_experiment_by_name(experiment)
    if exp is None:
        experiment_id = client.create_experiment(experiment)
    else:
        experiment_id = exp.experiment_id
    run_ids: dict[str, str] = {}
    for trial in trials:
        tags = {
            "endpoint_class": endpoint_class,
            "model": model or "env",
            "harbor_status": trial.status,
            "git_sha": _git_short_sha(settings.repo_root),
        }
        from shlepa_cli.mlflow_client import masked_client_stdout

        with masked_client_stdout():  # the client prints a View-run URL
            run = client.create_run(
                experiment_id=experiment_id, run_name=trial.task_name, tags=tags
            )
        run_id = run.info.run_id
        client.log_metric(run_id, "solved", 1.0 if trial.status == "solved" else 0.0)
        if trial.reward is not None:
            client.log_metric(run_id, "reward", trial.reward)
        if trial.tokens_in is not None:
            client.log_metric(run_id, "tokens_in", trial.tokens_in)
        if trial.tokens_out is not None:
            client.log_metric(run_id, "tokens_out", trial.tokens_out)
        if trial.duration_sec is not None:
            client.log_metric(run_id, "duration_sec", trial.duration_sec)
        if trial.error:
            client.log_param(run_id, "error", trial.error[:2000])
        client.set_terminated(run_id, status="FINISHED")
        run_ids[trial.task_name] = run_id
    return run_ids


def _default_runner(argv: list[str], env: dict[str, str]) -> tuple[int, str, str]:
    """Execute the Harbor argv; returns (returncode, stdout, stderr)."""
    full_env = {**os.environ, **env}
    proc = subprocess.run(argv, env=full_env, capture_output=True, text=True)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _tail(text: str, lines: int = 30) -> str:
    lines_list = text.splitlines()
    return "\n".join(lines_list[-lines:]) if lines_list else ""


def run_submit_test(
    settings,
    task_slugs: list[str] | None = None,
    *,
    ci: bool = False,
    out: Callable[[str], None] = print,
    mlflow_client=None,
    runner: Callable[[list[str], dict[str, str]], tuple[int, str, str]] | None = None,
) -> bool:
    """Run the strict contest-faithful test via Harbor; returns overall ok.

    Builds the submission zip (telemetry stripped), unzips it, and runs
    Harbor per task with the unzipped agent (in-container, acp image).
    Results are parsed from the job directory and optionally logged to
    MLflow (endpoint_class = main/ci).
    """
    from shlepa_cli import tasks as tasks_module
    from shlepa_cli.zip_build import build_submission_zip, ZipBuildError

    base_url, api_key, model, endpoint_class, experiment = resolve_endpoint(
        settings, ci=ci
    )
    if not model:
        out(
            "submit-test: no model configured "
            "(set LOCAL_AGENT_MODEL, or CI_MODEL for --ci)"
        )
        return False

    try:
        all_tasks = tasks_module.discover_tasks(settings.repo_root / "tasks")
    except ValueError as exc:
        out(f"submit-test: {exc}")
        return False
    if task_slugs:
        wanted = set(task_slugs)
        known = {t.slug for t in all_tasks}
        unknown = sorted(wanted - known)
        if unknown:
            out(f"submit-test: unknown task(s): {', '.join(unknown)}")
            return False
        selected = [t for t in all_tasks if t.slug in wanted]
    else:
        selected = all_tasks
    if not selected:
        out("submit-test: no tasks selected")
        return False

    out(
        f"submit-test: {len(selected)} task(s), model={model}, "
        f"endpoint_class={endpoint_class}, experiment={experiment}"
    )

    try:
        zip_path = build_submission_zip(settings.repo_root)
    except ZipBuildError as exc:
        out(f"submit-test: zip build failed: {exc}")
        return False
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = settings.repo_root / "tmp" / f"{stamp}-submit-test"
    agent_dir = unzip_submission(zip_path, workspace / "agent")
    out(f"submission: {zip_path.name} unzipped to {agent_dir}")

    use_runner = runner or _default_runner
    all_trials: list[HarborTrial] = []
    for task in selected:
        out(f"--- {task.slug} ---")
        jobs_dir = workspace / "jobs"
        argv, env = build_harbor_command(
            agent_dir=agent_dir,
            task_path=task.path,
            model=model,
            jobs_dir=jobs_dir,
            job_name=task.slug,
            base_url=base_url,
            api_key=api_key,
        )
        returncode, stdout, stderr = use_runner(argv, env)
        if returncode != 0:
            out(f"harbor failed (exit {returncode})")
            out(_tail(stderr or stdout))
            all_trials.append(
                HarborTrial(
                    task.slug, "error", None, None, None, None,
                    f"harbor exited with code {returncode}",
                )
            )
            continue
        try:
            job_dir = find_job_dir(jobs_dir, task.slug)
            trials = parse_job_dir(job_dir)
        except JobDirNotFound as exc:
            out(f"job directory not found: {exc}")
            all_trials.append(
                HarborTrial(task.slug, "error", None, None, None, None, str(exc))
            )
            continue
        if not trials:
            out("no trials found in job directory")
            all_trials.append(
                HarborTrial(
                    task.slug, "error", None, None, None, None, "no trials"
                )
            )
            continue
        for trial in trials:
            duration = (
                f", {trial.duration_sec:.0f}s" if trial.duration_sec is not None else ""
            )
            out(f"{trial.status}: {trial.task_name} (reward={trial.reward}{duration})")
        all_trials.extend(trials)

    if mlflow_client is not None:
        log_trials_to_mlflow(
            mlflow_client,
            settings,
            experiment=experiment,
            model=model,
            endpoint_class=endpoint_class,
            trials=all_trials,
        )
        out(f"mlflow: {len(all_trials)} run(s) logged to experiment '{experiment}'")

    n_solved = sum(1 for t in all_trials if t.status == "solved")
    ok = bool(all_trials) and all(t.status == "solved" for t in all_trials)
    out(f"submit-test: {n_solved}/{len(all_trials)} solved")
    return ok
