"""Typed settings for the shlepa CLI.

Resolves the repository root, loads .env from it (without overriding
variables already present in the environment), and exposes the
typed settings used by the commands.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import dotenv

_AGENT_DIR = "agent"


def find_repo_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (default: cwd) to the repo root.

    The root is the nearest directory containing both ``.git`` and
    ``agent/``.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() and (candidate / _AGENT_DIR).is_dir():
            return candidate
    raise FileNotFoundError(
        "shlepa repo root not found: no directory above "
        f"{current} contains both .git and {_AGENT_DIR}/"
    )


def load_env(root: Path | None = None) -> Path:
    """Load .env from the repo root; existing os.environ wins.

    Returns the repo root. A missing .env is not an error.
    """
    root = root or find_repo_root()
    env_file = root / ".env"
    if env_file.is_file():
        dotenv.load_dotenv(env_file, override=False)
    return root


@dataclass(frozen=True)
class Settings:
    """Typed snapshot of the environment (read after load_env)."""

    repo_root: Path
    openai_base_url: str | None
    openai_api_key: str | None
    local_agent_model: str | None
    ci_openai_base_url: str | None
    ci_openai_api_key: str | None
    ci_model: str | None
    mlflow_tracking_uri: str | None
    mlflow_tracking_username: str | None
    mlflow_tracking_password: str | None
    shlepa_otel_enabled: bool
    otel_exporter_otlp_endpoint: str | None
    mlflow_telemetry_experiment_id: str | None = None


def get_settings(root: Path | None = None) -> Settings:
    """Resolve the repo root, load .env, and snapshot the environment."""
    root = load_env(root)
    return Settings(
        repo_root=root,
        openai_base_url=os.environ.get("OPENAI_BASE_URL") or None,
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        local_agent_model=os.environ.get("LOCAL_AGENT_MODEL") or None,
        ci_openai_base_url=os.environ.get("CI_OPENAI_BASE_URL") or None,
        ci_openai_api_key=os.environ.get("CI_OPENAI_API_KEY") or None,
        ci_model=os.environ.get("CI_MODEL") or None,
        mlflow_tracking_uri=os.environ.get("MLFLOW_TRACKING_URI") or None,
        mlflow_tracking_username=os.environ.get("MLFLOW_TRACKING_USERNAME") or None,
        mlflow_tracking_password=os.environ.get("MLFLOW_TRACKING_PASSWORD") or None,
        shlepa_otel_enabled=os.environ.get("SLEPA_OTEL_ENABLED") == "1",
        otel_exporter_otlp_endpoint=(
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or None
        ),
        mlflow_telemetry_experiment_id=os.environ.get(
            "MLFLOW_TELEMETRY_EXPERIMENT_ID"
        ) or None,
    )
