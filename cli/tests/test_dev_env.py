"""Tests for the in-container dev agent environment (dev_env)."""

import subprocess
from pathlib import Path

from shlepa_cli import dev_env


def _make_agent_repo(base: Path) -> Path:
    agent = base / "agent"
    (agent / "shlepa_agent" / "telemetry").mkdir(parents=True)
    (agent / "tests").mkdir()
    (agent / "run.sh").write_text("#!/bin/bash\n")
    (agent / "agent.py").write_text("print('agent')\n")
    (agent / "pyproject.toml").write_text("[project]\n")
    (agent / "shlepa_agent" / "__init__.py").write_text("__version__ = '0.1.0'\n")
    (agent / "shlepa_agent" / "__main__.py").write_text("M = 1\n")
    (agent / "shlepa_agent" / "core.py").write_text("X = 1\n")
    (agent / "shlepa_agent" / "telemetry" / "__init__.py").write_text("T = 1\n")
    (agent / "tests" / "test_x.py").write_text("")
    (agent / "tools").mkdir()
    (agent / "tools" / "recon.py").write_text("print('recon')\n")
    return agent


def test_stage_agent_copies_only_the_package(tmp_path: Path) -> None:
    agent = _make_agent_repo(tmp_path)
    context = tmp_path / "ctx"

    dev_env.stage_agent(context, agent)

    assert (context / "dev_agent" / "shlepa_agent" / "core.py").is_file()
    # Telemetry ships into the dev image (local only, never zipped).
    assert (
        context / "dev_agent" / "shlepa_agent" / "telemetry" / "__init__.py"
    ).is_file()
    assert (context / "dev_agent" / "dev_run.py").is_file()
    # The tools/ helper scripts are staged next to the package so the
    # agent can run /agent/tools/recon.py inside the container.
    assert (context / "dev_agent" / "tools" / "recon.py").is_file()
    # Submission-only files are not part of the dev agent dir.
    assert not (context / "dev_agent" / "run.sh").exists()
    assert not (context / "dev_agent" / "agent.py").exists()
    assert not (context / "dev_agent" / "tests").exists()
    assert not (context / "dev_agent" / "pyproject.toml").exists()


def test_stage_agent_ignores_pycache(tmp_path: Path) -> None:
    agent = _make_agent_repo(tmp_path)
    pycache = agent / "shlepa_agent" / "__pycache__"
    pycache.mkdir()
    (pycache / "core.cpython-312.pyc").write_bytes(b"\x00")

    dev_env.stage_agent(tmp_path / "ctx", agent)

    assert not (tmp_path / "ctx" / "dev_agent" / "shlepa_agent" / "__pycache__").exists()


def test_write_dev_dockerfile(tmp_path: Path) -> None:
    dev_env.write_dev_dockerfile(
        tmp_path,
        "shlepa-task-hello-file:env",
        ["pydantic-ai-slim[openai]", "python-dotenv"],
    )
    text = (tmp_path / "Dockerfile").read_text()
    assert text.startswith("FROM shlepa-task-hello-file:env\n")
    assert "COPY dev_agent/ /agent/" in text
    # Build-time only: the telemetry enrichment package is pinned and
    # installed into the acp venv (which already has pydantic-ai + OTel).
    assert dev_env.OPENINFEERENCE_PIN in text
    # No-uv fallback: detect uv on PATH, then in the venv, otherwise
    # bootstrap the pinned static release.
    assert "command -v uv" in text
    assert f"{dev_env.AGENT_VENV}/bin/uv" in text
    assert (
        f"astral-sh/uv/releases/download/{dev_env.UV_BOOTSTRAP_VERSION}"
        in text
    )
    # No-venv fallback: env images without /app/.venv get a fresh agent
    # venv (uv-managed CPython) with the agent's own dependencies, extras
    # shell-quoted so '[' is never globbed.
    assert f"python install {dev_env.AGENT_VENV_PYTHON}" in text
    assert (
        f'venv {dev_env.AGENT_VENV} --python {dev_env.AGENT_VENV_PYTHON}'
        in text
    )
    assert "'pydantic-ai-slim[openai]'" in text
    assert "python-dotenv" in text
    # Old-glibc guard: the fresh venv gets a manylinux2014 tiktoken pin so
    # no Rust toolchain is needed on glibc 2.23 images.
    assert dev_env.TIKTOKEN_OLD_GLIBC_PIN in text


def test_write_dev_dockerfile_uv_download_fallbacks(tmp_path: Path) -> None:
    text = (tmp_path / "Dockerfile").write_text  # noqa: B018 - placeholder
    dev_env.write_dev_dockerfile(tmp_path, "shlepa-task-xyz:env", [])
    text = (tmp_path / "Dockerfile").read_text()
    # The ARVO base images ship neither curl nor wget: the uv download
    # falls back to python3's urllib.
    assert "curl -fsSL" in text
    assert "wget -q" in text
    assert "urllib.request.urlretrieve" in text
    # The pinned pin is still installed even without agent deps.
    assert dev_env.OPENINFEERENCE_PIN in text


def test_read_agent_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'dependencies = ["pydantic-ai-slim[openai]", "python-dotenv"]\n'
        "\n"
        "[project.optional-dependencies]\n"
        'telemetry = ['
        '"opentelemetry-sdk", '
        '"openinference-instrumentation-pydantic-ai"'
        "]\n"
    )
    deps = dev_env.read_agent_dependencies(tmp_path)
    # Telemetry extras are included (dev images are local-only) except the
    # openinference package, which is always installed from the pin.
    assert deps == [
        "pydantic-ai-slim[openai]",
        "python-dotenv",
        "opentelemetry-sdk",
    ]


def test_read_agent_dependencies_missing_pyproject(tmp_path: Path) -> None:
    assert dev_env.read_agent_dependencies(tmp_path) == []


def test_build_dev_image_builds_on_top_of_env_image(tmp_path: Path) -> None:
    class FakeDocker:
        def __init__(self) -> None:
            self.built = []

        def build(self, image: str, context: Path) -> None:
            self.built.append((image, context))

    agent = _make_agent_repo(tmp_path)
    docker = FakeDocker()

    image = dev_env.build_dev_image(
        docker,
        env_image="shlepa-task-hello-file:env",
        dev_image="shlepa-task-hello-file:dev",
        agent_dir=agent,
        workdir=tmp_path / "ws",
    )

    assert image == "shlepa-task-hello-file:dev"
    assert len(docker.built) == 1
    built_image, context = docker.built[0]
    assert built_image == "shlepa-task-hello-file:dev"
    assert (context / "Dockerfile").is_file()
    assert (context / "dev_agent" / "shlepa_agent" / "core.py").is_file()


def test_parse_agent_metrics() -> None:
    stderr = (
        "log line\n"
        'SLEPA_AGENT_METRICS_JSON={"final_output": "hello", '
        '"tokens_in": 5, "tokens_out": 7, "tool_calls": 2}\n'
        "trailing\n"
    )
    assert dev_env.parse_agent_metrics(stderr) == {
        "final_output": "hello",
        "tokens_in": 5,
        "tokens_out": 7,
        "tool_calls": 2,
        # legacy markers carry no cache fields -> stable 0s
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "phase_tokens": {},
        "termination": "ok",
    }


def test_parse_agent_metrics_carries_cache_fields() -> None:
    stderr = (
        'SLEPA_AGENT_METRICS_JSON={"final_output": "hello", '
        '"tokens_in": 1000, "tokens_out": 50, "tool_calls": 1, '
        '"tokens_cache_read": 750, "tokens_cache_write": 30}\n'
    )
    parsed = dev_env.parse_agent_metrics(stderr)
    assert parsed["tokens_cache_read"] == 750
    assert parsed["tokens_cache_write"] == 30


def test_parse_agent_metrics_missing_or_broken() -> None:
    defaults = {
        "final_output": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "tool_calls": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "phase_tokens": {},
        "termination": "ok",
    }
    assert dev_env.parse_agent_metrics("no marker") == defaults
    assert dev_env.parse_agent_metrics("") == defaults
    assert dev_env.parse_agent_metrics("SLEPA_AGENT_METRICS_JSON={broken") == defaults


def test_dev_run_source_sanity() -> None:
    # The generated entrypoint must be valid python and carry the marker.
    compile(dev_env.DEV_RUN_SOURCE, "dev_run.py", "exec")
    assert dev_env.METRICS_MARKER in dev_env.DEV_RUN_SOURCE
    assert '"/agent"' in dev_env.DEV_RUN_SOURCE
    # Telemetry on: the run must be wrapped in the agent.run root span.
    assert "root_span" in dev_env.DEV_RUN_SOURCE
    # The entrypoint must capture the cumulative cache fields from usage
    # events and report them in the metrics marker.
    assert "cumulative_cache_read" in dev_env.DEV_RUN_SOURCE
    assert "cumulative_cache_write" in dev_env.DEV_RUN_SOURCE
    assert '"tokens_cache_read"' in dev_env.DEV_RUN_SOURCE
    assert '"tokens_cache_write"' in dev_env.DEV_RUN_SOURCE


def test_run_agent_in_container_propagates_cache_metrics() -> None:
    from shlepa_cli.run_engine import AgentRun

    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "done", "tokens_in": 1000, "tokens_out": 50, '
        '"tool_calls": 1, "tokens_cache_read": 750, '
        '"tokens_cache_write": 30}\n'
    )
    fake = _ExecFakeDocker(rc=0, stderr=marker)
    run = dev_env.run_agent_in_container(fake, "c", "p", {}, timeout_sec=120)
    assert isinstance(run, AgentRun)
    assert run.tokens_cache_read == 750
    assert run.tokens_cache_write == 30


class _ExecFakeDocker:
    def __init__(self, rc=0, stdout="", stderr="") -> None:
        self.rc = rc
        self.stdout = stdout
        self.stderr = stderr
        self.execs: list[tuple[str, list[str], dict, object]] = []

    def exec(self, name, cmd, env, timeout=None):
        self.execs.append((name, cmd, dict(env), timeout))
        return subprocess.CompletedProcess(cmd, self.rc, stdout=self.stdout, stderr=self.stderr)


def test_run_agent_in_container_success() -> None:
    from shlepa_cli.run_engine import AgentRun

    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "hello.txt created", '
        '"tokens_in": 11, "tokens_out": 3, "tool_calls": 1}\n'
    )
    fake = _ExecFakeDocker(rc=0, stdout="hello.txt created", stderr=marker)
    run = dev_env.run_agent_in_container(
        fake,
        "container-1",
        "Create hello.txt",
        {"LOCAL_AGENT_WORKDIR": "/app", "LOCAL_AGENT_MODEL": "m"},
        timeout_sec=120,
    )
    assert isinstance(run, AgentRun)
    assert run.final_output == "hello.txt created"
    assert (run.tokens_in, run.tokens_out, run.tool_calls) == (11, 3, 1)
    name, cmd, env, timeout = fake.execs[0]
    assert name == "container-1"
    assert cmd == ["/app/.venv/bin/python", "/agent/dev_run.py", "Create hello.txt"]
    assert env["LOCAL_AGENT_WORKDIR"] == "/app"
    assert timeout == 240  # task timeout + 120s hard buffer


def test_run_agent_in_container_timeout_none_passes_none() -> None:
    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "x", "tokens_in": 1, "tokens_out": 1, '
        '"tool_calls": 0}\n'
    )
    fake = _ExecFakeDocker(stderr=marker)
    dev_env.run_agent_in_container(fake, "c", "p", {}, timeout_sec=None)
    assert fake.execs[0][3] is None


def test_run_agent_in_container_crash_raises() -> None:
    fake = _ExecFakeDocker(rc=1, stdout="", stderr="Traceback: boom")
    try:
        dev_env.run_agent_in_container(fake, "c", "p", {})
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "exited with code 1" in str(exc)
        assert "boom" in str(exc)


def test_run_agent_in_container_crash_carries_returncode() -> None:
    fake = _ExecFakeDocker(rc=137, stdout="", stderr="Killed")
    try:
        dev_env.run_agent_in_container(fake, "c", "p", {})
        raise AssertionError("expected AgentCrashError")
    except dev_env.AgentCrashError as exc:
        assert exc.returncode == 137
        assert "exited with code 137" in str(exc)


def test_dev_run_marks_crash_reason_on_root_span() -> None:
    # a crash (any non-timeout exception) must stamp the root span with
    # the exception class, not a bare 'crash'
    assert 'mark_termination(f"crash:{type(exc).__name__}")' in dev_env.DEV_RUN_SOURCE


def test_run_agent_in_container_marker_rescues_nonzero_exit() -> None:
    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "done", "tokens_in": 2, "tokens_out": 2, '
        '"tool_calls": 0}\n'
    )
    fake = _ExecFakeDocker(rc=1, stderr=marker)
    run = dev_env.run_agent_in_container(fake, "c", "p", {})
    assert run.final_output == "done"


def test_run_agent_in_container_ok_without_marker_uses_stdout() -> None:
    fake = _ExecFakeDocker(rc=0, stdout="answer line")
    run = dev_env.run_agent_in_container(fake, "c", "p", {})
    assert run.final_output == "answer line"
    assert (run.tokens_in, run.tokens_out, run.tool_calls) == (0, 0, 0)


def test_parse_agent_metrics_reports_termination() -> None:
    timeout_marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "", "tokens_in": 0, "tokens_out": 0, '
        '"tool_calls": 0, "termination": "timeout"}\n'
    )
    assert dev_env.parse_agent_metrics(
        timeout_marker
    )["termination"] == "timeout"
    assert dev_env.parse_agent_metrics("") == {
        "final_output": "",
        "tokens_in": 0,
        "tokens_out": 0,
        "tool_calls": 0,
        "tokens_cache_read": 0,
        "tokens_cache_write": 0,
        "phase_tokens": {},
        "termination": "ok",
    }


def test_run_agent_in_container_reports_timeout_termination() -> None:
    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "", "tokens_in": 0, "tokens_out": 0, '
        '"tool_calls": 0, "termination": "timeout"}\n'
    )
    fake = _ExecFakeDocker(rc=1, stderr="agent timed out after 5s\n" + marker)
    run = dev_env.run_agent_in_container(fake, "c", "p", {}, timeout_sec=5)
    assert run.termination == "timeout"
    assert run.final_output == ""


def test_run_agent_in_container_success_termination_is_ok() -> None:
    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "done", "tokens_in": 1, "tokens_out": 1, '
        '"tool_calls": 0}\n'
    )
    fake = _ExecFakeDocker(rc=0, stderr=marker)
    run = dev_env.run_agent_in_container(fake, "c", "p", {})
    assert run.termination == "ok"
    # legacy marker without cache fields -> 0s, not a crash
    assert run.tokens_cache_read == 0
    assert run.tokens_cache_write == 0


def test_dev_run_source_marks_internal_timeout() -> None:
    # The baked entrypoint must report its own wait_for expiry with a
    # termination=timeout marker (the e2e pass verifies it live), and the
    # v1 main-phase status 'done' must map to the engine's 'ok'.
    assert '"termination": "timeout"' in dev_env.DEV_RUN_SOURCE
    assert '"done": "ok"' in dev_env.DEV_RUN_SOURCE


# --- per-phase token capture (issue #73) -------------------------------------


def _dev_run_ns() -> dict:
    """Exec the baked dev entrypoint; return its module namespace."""
    ns = {"__name__": "dev_run_under_test"}
    exec(compile(dev_env.DEV_RUN_SOURCE, "dev_run.py", "exec"), ns)
    return ns


def _feed_capture(capture, event: str, **fields) -> None:
    import json
    import logging

    payload = {"event": event, **fields}
    rec = logging.LogRecord(
        "shlepa-agent", logging.INFO, "dev_run.py", 0, json.dumps(payload), None, None
    )
    capture.emit(rec)


def test_dev_run_capture_tracks_phase_token_deltas() -> None:
    """The baked entrypoint aggregates per-phase token deltas from
    phase-tagged cumulative usage events. Issue #73."""
    ns = _dev_run_ns()
    capture = ns["_MetricsCapture"]()
    # plan: two requests (cumulative counters are run-wide)
    _feed_capture(capture, "usage", phase="plan", cumulative_input=100,
                  cumulative_output=10, cumulative_cache_read=50,
                  cumulative_cache_write=5)
    _feed_capture(capture, "usage", phase="plan", cumulative_input=300,
                  cumulative_output=40, cumulative_cache_read=150,
                  cumulative_cache_write=20)
    # work: one request
    _feed_capture(capture, "usage", phase="work", cumulative_input=800,
                  cumulative_output=90, cumulative_cache_read=250,
                  cumulative_cache_write=20)
    # Totals keep their cumulative-last-value semantics
    assert (capture.tokens_in, capture.tokens_out) == (800, 90)
    assert capture.cache_read == 250
    assert capture.phase_tokens == {
        "plan": {"in": 300, "out": 40, "cache_read": 150},
        "work": {"in": 500, "out": 50, "cache_read": 100},
    }
    # per-phase tokens_in sums to the run total
    assert sum(p["in"] for p in capture.phase_tokens.values()) == capture.tokens_in


def test_dev_run_capture_legacy_usage_events_have_no_phase_buckets() -> None:
    """Legacy usage events (no phase field) produce no per-phase buckets
    and leave the totals unchanged. Issue #73."""
    ns = _dev_run_ns()
    capture = ns["_MetricsCapture"]()
    _feed_capture(capture, "usage", cumulative_input=100, cumulative_output=10)
    assert capture.phase_tokens == {}
    assert capture.tokens_in == 100


def test_parse_agent_metrics_carries_phase_tokens() -> None:
    stderr = (
        'SLEPA_AGENT_METRICS_JSON={"final_output": "hello", '
        '"tokens_in": 800, "tokens_out": 90, "tool_calls": 1, '
        '"phase_tokens": {"plan": {"in": 300, "out": 40, "cache_read": 150}, '
        '"work": {"in": 500, "out": 50, "cache_read": 100}}}\n'
    )
    parsed = dev_env.parse_agent_metrics(stderr)
    assert parsed["phase_tokens"]["plan"]["in"] == 300
    assert parsed["phase_tokens"]["work"]["cache_read"] == 100


def test_parse_agent_metrics_legacy_marker_phase_tokens_fresh_empty() -> None:
    """Legacy markers / missing markers yield an empty phase_tokens, with a
    fresh dict per call (no shared mutable default). Issue #73."""
    a = dev_env.parse_agent_metrics("")
    b = dev_env.parse_agent_metrics(
        'SLEPA_AGENT_METRICS_JSON={"final_output": "x", "tokens_in": 1, '
        '"tokens_out": 1, "tool_calls": 0}\n'
    )
    assert a["phase_tokens"] == {} and b["phase_tokens"] == {}
    assert a["phase_tokens"] is not b["phase_tokens"]


def test_run_agent_in_container_propagates_phase_tokens() -> None:
    from shlepa_cli.run_engine import AgentRun

    marker = (
        'SLEPA_AGENT_METRICS_JSON='
        '{"final_output": "done", "tokens_in": 800, "tokens_out": 90, '
        '"tool_calls": 1, "phase_tokens": '
        '{"plan": {"in": 300, "out": 40, "cache_read": 150}}}\n'
    )
    fake = _ExecFakeDocker(rc=0, stderr=marker)
    run = dev_env.run_agent_in_container(fake, "c", "p", {}, timeout_sec=120)
    assert isinstance(run, AgentRun)
    assert run.phase_tokens == {"plan": {"in": 300, "out": 40, "cache_read": 150}}
