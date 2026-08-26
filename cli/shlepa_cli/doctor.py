"""shlepa doctor: environment health checks.

Each check returns a CheckResult(ok, detail). Hard checks: LLM endpoint,
model match, MLflow, docker. The --probe chat completion is best effort
and never fails the run.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

import httpx

from shlepa_cli.config import Settings

HTTP_TIMEOUT = 10.0


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    model_expected: str | None = None
    model_actual: str | None = None


def check_llm_endpoint(settings: Settings) -> CheckResult:
    """GET {OPENAI_BASE_URL}/models succeeds (2xx)."""
    if not settings.openai_base_url:
        return CheckResult(
            "llm_endpoint", False, "OPENAI_BASE_URL is not set (see .env.example)"
        )
    url = f"{settings.openai_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.openai_api_key or ''}"}
    try:
        response = httpx.get(url, headers=headers, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        return CheckResult(
            "llm_endpoint", False, f"unreachable: {type(exc).__name__}: {exc}"
        )
    if response.status_code // 100 != 2:
        return CheckResult(
            "llm_endpoint",
            False,
            f"GET /models returned HTTP {response.status_code}",
        )
    return CheckResult("llm_endpoint", True, f"{url} -> HTTP {response.status_code}")


def check_llm_model(settings: Settings) -> CheckResult:
    """LOCAL_AGENT_MODEL is listed by GET {OPENAI_BASE_URL}/models."""
    if not settings.openai_base_url:
        return CheckResult("llm_model", False, "OPENAI_BASE_URL is not set")
    expected = settings.local_agent_model or ""
    url = f"{settings.openai_base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {settings.openai_api_key or ''}"}
    try:
        response = httpx.get(url, headers=headers, timeout=HTTP_TIMEOUT)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return CheckResult(
            "llm_model", False, f"could not list models: {exc}", expected, None
        )
    actual_models = [m.get("id") for m in payload.get("data", [])]
    if expected in actual_models:
        return CheckResult(
            "llm_model",
            True,
            f"{expected!r} is served",
            expected,
            ", ".join(actual_models) or None,
        )
    return CheckResult(
        "llm_model",
        False,
        (
            f"model mismatch: LOCAL_AGENT_MODEL={expected!r} is not served "
            f"by the endpoint (served: {', '.join(actual_models) or 'none'})"
        ),
        expected,
        ", ".join(actual_models) or None,
    )


def check_mlflow(
    settings: Settings,
    client_factory: Callable[[Settings], object] | None = None,
) -> CheckResult:
    """MLflow server responds to a read-only version request."""
    if client_factory is None:
        from shlepa_cli.mlflow_client import get_mlflow_client

        client_factory = get_mlflow_client
    if not settings.mlflow_tracking_uri:
        return CheckResult(
            "mlflow", False, "MLFLOW_TRACKING_URI is not set (see .env.example)"
        )
    try:
        client = client_factory(settings)
        version = client.get_version()
    except Exception as exc:  # noqa: BLE001 - report any failure as FAIL
        return CheckResult("mlflow", False, f"unreachable: {type(exc).__name__}: {exc}")
    return CheckResult("mlflow", True, f"server version {version}")


def check_docker(settings: Settings) -> CheckResult:
    """Docker binary present and daemon responsive."""
    if shutil.which("docker") is None:
        return CheckResult("docker", False, "docker binary not found in PATH")
    try:
        proc = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckResult("docker", False, f"docker query failed: {exc}")
    if proc.returncode != 0:
        return CheckResult(
            "docker",
            False,
            f"docker daemon not responsive: {proc.stderr.strip()}",
        )
    return CheckResult("docker", True, f"server {proc.stdout.strip()}")


def probe_chat(settings: Settings) -> str:
    """One best-effort chat completion; returns a display string, never raises."""
    if not settings.openai_base_url:
        return "skipped (OPENAI_BASE_URL not set)"
    url = f"{settings.openai_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.openai_api_key or ''}"}
    body = {
        "model": settings.local_agent_model or "default",
        "messages": [{"role": "user", "content": "Reply with the single word ok."}],
        "max_tokens": 8,
        "stream": False,
    }
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=30.0)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return f"failed ({type(exc).__name__})"
    model = payload.get("model", "unknown")
    content = (
        payload.get("choices") or [{}]
    )[0].get("message", {}).get("content", "")
    return f"ok (model={model}, reply={content!r})"


def run_doctor(
    settings: Settings,
    probe: bool = False,
    client_factory: Callable[[Settings], object] | None = None,
) -> tuple[list[CheckResult], str | None]:
    """Run all hard checks (and optionally the chat probe).

    Returns (results, probe_info).
    """
    results = [
        check_llm_endpoint(settings),
        check_llm_model(settings),
        check_mlflow(settings, client_factory=client_factory),
        check_docker(settings),
    ]
    probe_info = probe_chat(settings) if probe else None
    return results, probe_info
