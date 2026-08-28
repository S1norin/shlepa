"""Register a built submission zip in the MLflow model registry."""

import tarfile
from pathlib import Path

from mlflow.exceptions import MlflowException

from shlepa_cli import zip_build
from shlepa_cli.config import Settings
from shlepa_cli.mlflow_client import masked_client_stdout

MODEL_NAME = "shlepa"
# Dedicated experiment for submission registrations; the remote MLflow
# server has its Default (experiment 0) deleted, so we never rely on it.
SUBMISSION_EXPERIMENT = "shlepa-submissions"


def _get_or_create_experiment(client, name: str) -> str:
    exp = client.get_experiment_by_name(name)
    if exp is None:  # MLflow 3 returns None for a missing experiment
        return str(client.create_experiment(name))
    return str(exp.experiment_id)


# Development cruft excluded from the source tarball (the venv alone is
# ~85 MB; the server-side artifact upload would never finish with it).
_TARBALL_EXCLUDE = {".venv", "__pycache__", ".pytest_cache"}


def _tarball_filter(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(member.name).name
    if name in _TARBALL_EXCLUDE:
        return None  # rejects the whole subtree when it is a directory
    return member


def make_agent_tarball(repo_root: Path, out_path: Path) -> Path:
    """Pack repo_root/agent source into a tar.gz.

    The full source (telemetry included) is kept alongside the stripped
    zip so versions can be code-diffed against the actual development
    tree; venvs and caches are excluded (they are not source).
    """
    with tarfile.open(out_path, "w:gz") as tf:
        tf.add(repo_root / "agent", arcname="agent", filter=_tarball_filter)
    return out_path


def register_submission(client, settings: Settings, zip_path: Path) -> str:
    """Register ``zip_path`` as a new version of the 'shlepa' model.

    Ensures the registered model exists, logs the zip and the full agent
    source tarball as artifacts of a dedicated run, creates a model
    version from that run, and sets the git_sha / model tags. Returns the
    new version number as a string.
    """
    try:
        client.get_registered_model(MODEL_NAME)
    except MlflowException:
        client.create_registered_model(MODEL_NAME)

    tar_path = zip_path.with_name(f"{zip_path.stem}.agent.tar.gz")
    make_agent_tarball(settings.repo_root, tar_path)

    experiment_id = _get_or_create_experiment(client, SUBMISSION_EXPERIMENT)
    with masked_client_stdout():  # the client prints a View-run URL
        run = client.create_run(
            experiment_id=experiment_id, run_name=f"submission-{zip_path.stem}"
        )
    run_id = run.info.run_id
    try:
        client.log_artifact(run_id, str(zip_path))
        client.log_artifact(run_id, str(tar_path))
    finally:
        client.set_terminated(run_id, status="FINISHED")

    model_version = client.create_model_version(
        MODEL_NAME, source=f"runs:/{run_id}", run_id=run_id
    )
    version = str(model_version.version)
    sha = zip_build._git_short_sha(settings.repo_root)
    client.set_model_version_tag(
        MODEL_NAME, version, "git_sha", sha or "unknown"
    )
    client.set_model_version_tag(
        MODEL_NAME, version, "model", settings.local_agent_model or "env"
    )
    return version
