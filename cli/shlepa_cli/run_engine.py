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
import logging
import os
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path

from shlepa_cli import mlflow_compat as compat
from shlepa_cli.config import Settings
from shlepa_cli.tasks import Task, task_family

DEFAULT_TRACE_EXPERIMENT = "shlepa-traces"
AGENT_SERVICE = "shlepa-agent"


@dataclass(frozen=True)
class AgentRun:
    """Outcome of one agent execution.

    ``termination`` is one of 'ok', 'budget' (the v1 main phase hit its
    budget and handed off to the commit phase), 'error' (the main run
    failed; the process still exited 0), 'timeout' (the agent's own
    wait_for expired), 'exec_timeout' (the docker exec hard timeout hit)
    or 'crash' (the agent died without a metrics marker).
    """

    final_output: str
    tokens_in: int
    tokens_out: int
    tool_calls: int
    termination: str = "ok"
    # Cache subset of the input tokens (0 when the endpoint doesn't
    # report them); appended so positional constructors stay valid.
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    # Per-phase token deltas: phase id -> {"in", "out", "cache_read"}
    # ({} for legacy runs without phase-tagged usage events). Issue #73.
    phase_tokens: dict = field(default_factory=dict)


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
    termination: str = "ok"
    tokens_cache_read: int = 0
    tokens_cache_write: int = 0
    # Per-phase token deltas ({} for legacy runs). Issue #73.
    phase_tokens: dict = field(default_factory=dict)


def make_workspace(repo_root: Path, slug: str) -> Path:
    """Create tmp/<YYYYMMDD-HHMMSS>-<slug>/ under the repo root."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = Path(repo_root) / "tmp" / f"{timestamp}-{slug}"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def make_batch_id() -> str:
    """Batch id for one 'shlepa run' invocation: <UTCcompact>-<6hex>."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{secrets.token_hex(3)}"


class _HostMetricsCapture(logging.Handler):
    """Collect token/tool metrics from the agent's JSON event log.

    The runner logs a ``usage`` event with cumulative tokens after each
    model request and a ``llm_tool_call`` event per tool invocation.
    """

    def __init__(self) -> None:
        super().__init__()
        self.tokens_in = 0
        self.tokens_out = 0
        self.cache_read = 0
        self.cache_write = 0
        self.tool_calls = 0
        # Per-phase deltas from phase-tagged cumulative usage events
        # ({} for legacy events without a phase). Issue #73.
        self.phase_tokens: dict = {}
        self._last_in = 0
        self._last_out = 0
        self._last_cache_read = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            data = json.loads(record.getMessage())
        except (TypeError, ValueError):
            return
        event = data.get("event")
        if event == "usage":
            ci = int(data.get("cumulative_input") or 0)
            co = int(data.get("cumulative_output") or 0)
            cr = int(data.get("cumulative_cache_read") or 0)
            self.tokens_in = ci
            self.tokens_out = co
            self.cache_read = cr
            self.cache_write = int(data.get("cumulative_cache_write") or 0)
            phase = data.get("phase")
            if phase:
                bucket = self.phase_tokens.setdefault(
                    phase, {"in": 0, "out": 0, "cache_read": 0}
                )
                bucket["in"] += max(0, ci - self._last_in)
                bucket["out"] += max(0, co - self._last_out)
                bucket["cache_read"] += max(0, cr - self._last_cache_read)
            self._last_in = ci
            self._last_out = co
            self._last_cache_read = cr
        elif event == "llm_tool_call":
            self.tool_calls += 1


def run_agent_on_host(
    instruction: str,
    workdir: Path,
    model: str | None,
    timeout_sec: int | None,
    otel_enabled: bool,
) -> AgentRun:
    """Run the shlepa agent on the host against one instruction.

    Env vars for the agent come from the process environment (the CLI
    loads .env at startup); LOCAL_AGENT_MODEL and LOCAL_AGENT_WORKDIR
    are overridden for the duration of the run. Works like the
    in-container path: runner.run_prompt runs the budgeted agent (phase
    graph plus the emergency commit phase) and never raises on budget;
    an outer
    wait_for timeout still surfaces as TimeoutError.
    """
    from shlepa_agent import runner
    from shlepa_agent.log import LOGGER, _configure_logging

    capture = _HostMetricsCapture()
    _configure_logging()
    LOGGER.addHandler(capture)
    old_model = os.environ.get("LOCAL_AGENT_MODEL")
    old_workdir = os.environ.get("LOCAL_AGENT_WORKDIR")
    if model:
        os.environ["LOCAL_AGENT_MODEL"] = model
    os.environ["LOCAL_AGENT_WORKDIR"] = str(workdir)
    try:
        try:
            output = asyncio.run(
                asyncio.wait_for(
                    runner.run_prompt(instruction, instrument=otel_enabled),
                    timeout=timeout_sec,
                )
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"agent timed out after {timeout_sec}s") from None
    finally:
        if old_model is None:
            os.environ.pop("LOCAL_AGENT_MODEL", None)
        else:
            os.environ["LOCAL_AGENT_MODEL"] = old_model
        if old_workdir is None:
            os.environ.pop("LOCAL_AGENT_WORKDIR", None)
        else:
            os.environ["LOCAL_AGENT_WORKDIR"] = old_workdir
        LOGGER.removeHandler(capture)

    return AgentRun(
        final_output=output,
        tokens_in=capture.tokens_in,
        tokens_out=capture.tokens_out,
        tokens_cache_read=capture.cache_read,
        tokens_cache_write=capture.cache_write,
        tool_calls=capture.tool_calls,
        phase_tokens=capture.phase_tokens,
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


def _resolve_trace_experiment_id(client, settings: Settings) -> str | None:
    """Experiment id where agent traces land (name or numeric id)."""
    exp = settings.mlflow_telemetry_experiment_id
    if exp:
        if exp.isdigit():
            return exp
        found = client.get_experiment_by_name(exp)
        return found.experiment_id if found is not None else None
    found = client.get_experiment_by_name(DEFAULT_TRACE_EXPERIMENT)
    return found.experiment_id if found is not None else None


def find_batch_trace(
    client,
    settings: Settings,
    batch_id: str,
    task_slug: str,
    since_ms: int | None = None,
    max_results: int = 50,
) -> str | None:
    """Find the trace of one task in this batch; returns its id or None.

    Candidate filtering uses only trace-level data (service.name tag +
    request_time window); a span-level shlepa.batch_id/task match decides.
    Never raises: the caller treats None as 'not found yet'.
    """
    try:
        exp_id = _resolve_trace_experiment_id(client, settings)
        if exp_id is None:
            return None
        return _find_batch_trace_inner(
            client, exp_id, batch_id, task_slug, since_ms, max_results
        )
    except Exception:  # noqa: BLE001 - lookup must never fail the run
        return None


def _find_batch_trace_inner(
    client,
    exp_id: str,
    batch_id: str,
    task_slug: str,
    since_ms: int | None,
    max_results: int,
) -> str | None:
    paged = compat.search_experiment_traces(client, exp_id, max_results)
    for trace in paged:  # PagedList is list-like; fakes may be plain lists
        info = trace.info
        tags = getattr(info, "tags", None) or {}
        if tags.get("service.name") != AGENT_SERVICE:
            continue
        if since_ms is not None and (info.request_time or 0) < since_ms:
            continue
        if tags.get("shlepa.batch_id") == batch_id:
            # Server promoted span attributes to trace tags: fast path.
            return info.trace_id
        try:
            fetched = client.get_trace(info.trace_id)
        except Exception:  # noqa: BLE001
            continue
        spans = getattr(getattr(fetched, "data", None), "spans", None) or []
        attrs = [dict(span.attributes or {}) for span in spans]
        if any(a.get("shlepa.batch_id") == batch_id for a in attrs) and any(
            a.get("task") == task_slug for a in attrs
        ):
            return info.trace_id
    return None


def record_trace_tag(
    client,
    settings: Settings,
    run_id: str,
    batch_id: str,
    task_slug: str,
    batch_started_ms: int | None = None,
    timeout_sec: float = 15.0,
) -> str | None:
    """Retry the batch trace lookup (the collector exports with a lag)
    and store the trace id in the run tag ``mlflow_trace_id``, then
    link the trace to the run so the run UI shows it.

    A missing trace is not an error: warn and omit the tag. A failed
    link is not an error either: warn and keep the tag.
    """
    deadline = time.monotonic() + max(timeout_sec, 0.0)
    while True:
        trace_id = find_batch_trace(
            client, settings, batch_id, task_slug, since_ms=batch_started_ms
        )
        if trace_id is not None:
            client.set_tag(run_id, "mlflow_trace_id", trace_id)
            _link_trace_to_run(client, run_id, trace_id)
            return trace_id
        if time.monotonic() >= deadline:
            break
        time.sleep(min(3.0, deadline - time.monotonic()))
    print(
        f"  ! no MLflow trace found for batch {batch_id} "
        f"task {task_slug} (mlflow_trace_id tag omitted)",
        flush=True,
    )
    return None


def _link_trace_to_run(client, run_id: str, trace_id: str) -> None:
    """Link a found trace to its MLflow run (best effort).

    Uses ``MlflowClient.link_traces_to_run`` when the client has it
    (mlflow >= 3.15); older clients skip silently. A link failure must
    never fail the run: warn and continue.
    """
    link = getattr(client, "link_traces_to_run", None)
    if link is None:
        return
    try:
        link(trace_ids=[trace_id], run_id=run_id)
    except Exception as exc:  # noqa: BLE001 - telemetry must not fail runs
        print(
            f"  ! failed to link trace {trace_id} to run {run_id} "
            f"({type(exc).__name__}: {exc}); mlflow_trace_id tag kept",
            flush=True,
        )


def log_task_to_mlflow(
    client,
    settings: Settings,
    preset_name: str,
    model: str | None,
    result: TaskResult,
    endpoint_class: str = "main",
    batch_id: str | None = None,
    batch_started_ms: int | None = None,
    trace_wait_sec: float = 15.0,
    experiment_name: str | None = None,
) -> str:
    """Log one task result as an MLflow run; returns the run id.

    experiment = task family (derived from the slug via ``task_family``),
    run name = task slug. The preset is kept only as a tag so per-bench
    analysis groups runs by family while preset-scoped filtering still
    works. ``experiment_name`` overrides the family derivation for callers
    that log to a fixed experiment (smoke/CI); the preset tag always
    reflects ``preset_name``. With otel on and a ``batch_id`` given, the
    run is tagged with ``batch_id`` and (when the trace is found)
    ``mlflow_trace_id``.
    """
    import shlepa_agent

    family = experiment_name or task_family(result.slug)
    experiment = client.get_experiment_by_name(family)
    if experiment is None:
        experiment_id = client.create_experiment(family)
    else:
        experiment_id = experiment.experiment_id
    tags = {
        "preset": preset_name,
        "model": model or "env",
        "agent_version": shlepa_agent.__version__,
        "git_sha": _git_sha(settings.repo_root),
        "endpoint_class": endpoint_class,
    }
    if batch_id:
        tags["batch_id"] = batch_id
    if settings.shlepa_otel_enabled:
        jaeger = (settings.otel_exporter_otlp_endpoint or "http://localhost:4318").replace(
            ":4318", ":16686"
        )
        tags["trace_ref"] = f"{jaeger} service=shlepa-agent task={result.slug}"
    from shlepa_cli.mlflow_client import masked_client_stdout

    with masked_client_stdout():  # defensive: mask any raw client output
        run = client.create_run(
            experiment_id=experiment_id, run_name=result.slug, tags=tags
        )
    run_id = run.info.run_id
    # The library's own View-run URL carries the embedded basic-auth
    # credentials; print a clean one instead (host without userinfo).
    parts = urlsplit(settings.mlflow_tracking_uri or "")
    host = parts.hostname or ""
    if parts.port is not None:
        host += f":{parts.port}"
    if host:
        print(
            f"mlflow run: https://{host}/#/experiments/{experiment_id}/runs/{run_id}",
            flush=True,
        )
    client.log_metric(run_id, "solved", 1.0 if result.solved else 0.0)
    client.log_metric(run_id, "duration_sec", result.duration_sec)
    client.log_metric(run_id, "tokens_in", result.tokens_in)
    client.log_metric(run_id, "tokens_out", result.tokens_out)
    client.log_metric(run_id, "tokens_total", result.tokens_total)
    # Always logged (0 when the endpoint doesn't report cache) so the
    # runs table schema is stable across endpoint classes.
    client.log_metric(run_id, "tokens_cache_read", result.tokens_cache_read)
    client.log_metric(run_id, "tokens_cache_write", result.tokens_cache_write)
    # Per-phase token deltas for every phase that ran (legacy runs have
    # no phase data and keep their metric shape). Issue #73.
    for phase, tokens in (result.phase_tokens or {}).items():
        client.log_metric(run_id, f"tokens_in.{phase}", tokens.get("in", 0))
        client.log_metric(run_id, f"tokens_out.{phase}", tokens.get("out", 0))
        client.log_metric(
            run_id, f"tokens_cache_read.{phase}", tokens.get("cache_read", 0)
        )
    client.log_metric(run_id, "tool_calls", result.tool_calls)
    client.log_param(run_id, "final_output", result.final_output[:2000])
    client.log_param(run_id, "termination", result.termination)
    if result.error:
        client.log_param(run_id, "error", result.error[:2000])
    result_json = result.workspace / "result.json"
    if result_json.is_file():
        client.log_artifact(run_id, str(result_json), artifact_path="data")
    if settings.shlepa_otel_enabled and batch_id:
        record_trace_tag(
            client,
            settings,
            run_id,
            batch_id,
            result.slug,
            batch_started_ms=batch_started_ms,
            timeout_sec=trace_wait_sec,
        )
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
    batch_id: str | None = None,
) -> list[TaskResult]:
    """Run every task of a preset; a failing task never stops the batch.

    Each task result is logged to MLflow when ``mlflow_client`` is given.
    One batch id per invocation (generated when not given) correlates the
    MLflow runs with the agent traces.
    """
    batch_id = batch_id or make_batch_id()
    batch_started_ms = int(time.time() * 1000)
    if settings.shlepa_otel_enabled:
        endpoint = (
            settings.otel_exporter_otlp_endpoint or "http://localhost:4318"
        )
        if not _probe_collector(endpoint):
            print(
                f"warning: OTel collector unreachable (probed {endpoint}) "
                "\u2014 agent traces will be LOST for this batch; start it with "
                "docker compose -f otel/docker-compose.yml up -d",
                file=sys.stderr,
                flush=True,
            )
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
            batch_id=batch_id,
            preset_name=preset.name,
        )
        results.append(result)
        if mlflow_client is not None:
            log_task_to_mlflow(
                mlflow_client,
                settings,
                preset.name,
                model,
                result,
                batch_id=batch_id,
                batch_started_ms=batch_started_ms,
            )
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
    batch_id: str | None = None,
    preset_name: str | None = None,
) -> AgentRun:
    """Invoke the agent with SLEPA_TASK_SLUG set for the duration of the run.

    Host mode: the telemetry identity env (SLEPA_BATCH_ID and friends)
    reaches the in-process agent through os.environ, like SLEPA_TASK_SLUG.
    """
    old_slug = os.environ.get("SLEPA_TASK_SLUG")
    os.environ["SLEPA_TASK_SLUG"] = task.slug
    extra: dict[str, str] = {}
    if settings.shlepa_otel_enabled:
        if batch_id:
            extra["SLEPA_BATCH_ID"] = batch_id
        if preset_name:
            extra["SLEPA_PRESET"] = preset_name
        extra["SLEPA_GIT_SHA"] = _git_sha(settings.repo_root)
        extra["SLEPA_AGENT_VERSION"] = _agent_version()
    old_extra = {k: os.environ.get(k) for k in extra}
    os.environ.update(extra)
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
        for key, value in old_extra.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


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


def _probe_collector(endpoint: str) -> bool:
    """One cheap GET to the collector's health_check extension (13133).

    Never raises: any failure simply means "unreachable". The probe is
    a warning aid only; it must not fail a run.
    """
    from urllib.parse import urlsplit
    from urllib.request import urlopen

    parts = urlsplit(endpoint or "")
    host = parts.hostname or "localhost"
    try:
        with urlopen(f"http://{host}:13133/", timeout=1) as resp:
            return getattr(resp, "status", 200) == 200
    except Exception:  # noqa: BLE001 - probe must never break the run
        return False


def _classify_termination(exc: Exception) -> str:
    """Map a run exception to a termination reason.

    'exec_timeout' for docker exec hard timeouts, 'oom' for OOM-killed
    containers (exit 137 / signal 9), 'crash' for everything else.
    """
    if "timeout" in type(exc).__name__.lower():
        # The docker exec hard timeout (agent timeout + 120s buffer)
        # fired; the in-container wait_for did not.
        return "exec_timeout"
    if getattr(exc, "returncode", None) in (137, -9):
        # docker exec reports the container's exit code; 137 = SIGKILL,
        # the usual OOM-kill signature.
        return "oom"
    return "crash"


def _agent_env(
    settings: Settings,
    model: str | None,
    task: Task,
    batch_id: str | None = None,
    preset_name: str | None = None,
) -> dict[str, str]:
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
        if batch_id:
            env["SLEPA_BATCH_ID"] = batch_id
        if preset_name:
            env["SLEPA_PRESET"] = preset_name
        env["SLEPA_GIT_SHA"] = _git_sha(settings.repo_root)
        env["SLEPA_AGENT_VERSION"] = _agent_version()
    return env


def _agent_version() -> str:
    """Installed shlepa_agent version ('unknown' if not importable)."""
    try:
        import shlepa_agent

        return shlepa_agent.__version__
    except Exception:  # noqa: BLE001 - version is best-effort identity
        return "unknown"


def run_task(
    task: Task,
    settings: Settings,
    *,
    model: str | None,
    no_docker: bool = True,
    agent_runner=None,
    docker_client=None,
    batch_id: str | None = None,
    preset_name: str | None = None,
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
                batch_id=batch_id,
                preset_name=preset_name,
            )
            solved, score_detail = _score_no_docker(task, workspace)
        except Exception as exc:  # noqa: BLE001 - keep the batch going
            error = f"{type(exc).__name__}: {exc}"
            agent_run = AgentRun(
                "", 0, 0, 0, termination=_classify_termination(exc)
            )
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
                _agent_env(settings, model, task, batch_id=batch_id, preset_name=preset_name),
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
            agent_run = AgentRun(
                "", 0, 0, 0, termination=_classify_termination(exc)
            )
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
        tokens_cache_read=agent_run.tokens_cache_read,
        tokens_cache_write=agent_run.tokens_cache_write,
        phase_tokens=agent_run.phase_tokens,
        tool_calls=agent_run.tool_calls,
        final_output=agent_run.final_output,
        error=error,
        score_detail=score_detail,
        workspace=workspace,
        termination=agent_run.termination,
    )
    _write_result_json(workspace, result)
    return result
