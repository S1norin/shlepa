"""shlepa doctor: environment health checks.

Each check returns a CheckResult(ok, detail). Hard checks: LLM endpoint,
model match, MLflow, MLflow OTLP ingestion (when SLEPA_OTEL_ENABLED=1),
docker. The --probe chat completion is best effort and never fails the run.
"""

from __future__ import annotations

import base64
import secrets
import shutil
import subprocess
import time
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
        # read-only request; MLflow 3's client has no get_version() method
        client.search_experiments(max_results=1)
    except Exception as exc:  # noqa: BLE001 - report any failure as FAIL
        return CheckResult("mlflow", False, f"unreachable: {type(exc).__name__}: {exc}")
    return CheckResult("mlflow", True, "server reachable")


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


def _basic_auth_header(username: str, password: str | None) -> str:
    raw = f"{username}:{password or ''}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _otlp_probe_payload() -> dict:
    """Minimal OTLP/HTTP JSON body with one no-op span (doctor probe).

    The probe lands in the telemetry experiment as service 'shlepa-doctor';
    trace lookups filter on service 'shlepa-agent', so it never interferes.
    """
    now_ns = time.time_ns()
    trace_id = secrets.token_hex(16)
    span_id = secrets.token_hex(8)
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "shlepa-doctor"}}
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "shlepa-doctor"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "doctor.otlp.probe",
                                "kind": 1,
                                "startTimeUnixNano": str(now_ns),
                                "endTimeUnixNano": str(now_ns),
                            }
                        ],
                    }
                ],
            }
        ]
    }


def check_mlflow_otlp(settings: Settings) -> CheckResult:
    """MLflow OTLP ingestion: GET /version (+ no-op POST /v1/traces).

    Only runs when SLEPA_OTEL_ENABLED=1 (the collector is the one that
    exports to the remote server, so this is the dev-only path). Reports
    HTTP-level failures without leaking credentials.
    """
    if not settings.shlepa_otel_enabled:
        return CheckResult(
            "mlflow_otlp", True, "skipped (SLEPA_OTEL_ENABLED not set)"
        )
    if not settings.mlflow_tracking_uri:
        return CheckResult(
            "mlflow_otlp", False, "MLFLOW_TRACKING_URI is not set"
        )
    headers: dict[str, str] = {}
    if settings.mlflow_tracking_username:
        headers["Authorization"] = _basic_auth_header(
            settings.mlflow_tracking_username,
            settings.mlflow_tracking_password,
        )
    base = settings.mlflow_tracking_uri.rstrip("/")
    try:
        version_resp = httpx.get(f"{base}/version", headers=headers, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        return CheckResult(
            "mlflow_otlp", False, f"unreachable: {type(exc).__name__}: {exc}"
        )
    if version_resp.status_code // 100 != 2:
        return CheckResult(
            "mlflow_otlp",
            False,
            f"GET /version returned HTTP {version_resp.status_code}",
        )
    version = version_resp.text.strip() or "(version unknown)"
    if not settings.mlflow_telemetry_experiment_id:
        return CheckResult(
            "mlflow_otlp",
            True,
            (
                f"server {version} "
                "(POST /v1/traces skipped: MLFLOW_TELEMETRY_EXPERIMENT_ID not set)"
            ),
        )
    post_headers = {
        **headers,
        "Content-Type": "application/json",
        "x-mlflow-experiment-id": settings.mlflow_telemetry_experiment_id,
    }
    try:
        resp = httpx.post(
            f"{base}/v1/traces",
            headers=post_headers,
            json=_otlp_probe_payload(),
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        return CheckResult(
            "mlflow_otlp", False, f"POST /v1/traces failed: {type(exc).__name__}: {exc}"
        )
    if resp.status_code // 100 != 2:
        return CheckResult(
            "mlflow_otlp",
            False,
            f"POST /v1/traces returned HTTP {resp.status_code}",
        )
    return CheckResult("mlflow_otlp", True, f"server {version}, OTLP ingestion OK")


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
        check_mlflow_otlp(settings),
        check_docker(settings),
    ]
    probe_info = probe_chat(settings) if probe else None
    return results, probe_info
