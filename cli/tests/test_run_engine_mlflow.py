"""Run engine tests: MLflow run logging (file:// store)."""

from pathlib import Path

import pytest

from mlflow import MlflowClient

from shlepa_cli import run_engine
from shlepa_cli.config import Settings
from shlepa_cli.tasks import Preset, Task


@pytest.fixture(autouse=True)
def _allow_file_store(monkeypatch):
    # MLflow 3.x keeps the file store in maintenance mode behind an opt-in.
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")


def _settings(root):
    return Settings(
        repo_root=root,
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model=None,
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )


def _result(tmp_path, **overrides):
    base = dict(
        slug="contest-hello-file",
        ok=True,
        solved=True,
        duration_sec=1.25,
        tokens_in=10,
        tokens_out=5,
        tokens_total=15,
        tool_calls=2,
        final_output="Created hello.txt",
        error=None,
        score_detail="",
        workspace=tmp_path,
    )
    base.update(overrides)
    return run_engine.TaskResult(**base)


class _PrintingClient:
    """Fake client that mimics the MLflow library printing a View-run
    URL (with the tracking URI's embedded credentials) to stdout at
    create_run time."""

    def __init__(self):
        self.metrics = {}

    def create_experiment(self, name):
        return "99"

    def get_experiment_by_name(self, name):
        return type("Exp", (), {"experiment_id": "99", "name": name})()

    def create_run(self, experiment_id, run_name, tags=None):
        import sys

        sys.stdout.write(
            "🏃 View run x at: "
            "https://user:secretpass@mlflow.example/#/experiments/99/runs/r1\n"
        )
        info = type("Info", (), {"run_id": "r1"})()
        return type("Run", (), {"info": info})()

    def log_metric(self, run_id, key, value, **kwargs):
        self.metrics[key] = value

    def log_artifact(self, *args, **kwargs):
        pass

    def log_param(self, *args, **kwargs):
        pass

    def set_terminated(self, *args, **kwargs):
        pass


def test_log_task_to_mlflow_cache_metrics_when_present(tmp_path):
    client = _PrintingClient()
    run_engine.log_task_to_mlflow(
        client,
        _settings(tmp_path),
        "all",
        None,
        _result(tmp_path, tokens_cache_read=120, tokens_cache_write=8),
    )
    assert client.metrics["tokens_cache_read"] == 120
    assert client.metrics["tokens_cache_write"] == 8


def test_log_task_to_mlflow_cache_metrics_zero_when_absent(tmp_path):
    """Stable schema: cache metrics are logged as 0, not omitted (issue #71)."""
    client = _PrintingClient()
    run_engine.log_task_to_mlflow(
        client, _settings(tmp_path), "all", None, _result(tmp_path)
    )
    assert client.metrics["tokens_cache_read"] == 0
    assert client.metrics["tokens_cache_write"] == 0


def test_log_task_to_mlflow_masks_view_run_url(tmp_path, capsys):
    client = _PrintingClient()
    run_id = run_engine.log_task_to_mlflow(
        client, _settings(tmp_path), "all", None, _result(tmp_path)
    )
    out = capsys.readouterr().out
    assert run_id == "r1"
    assert "secretpass" not in out
    assert "https://user:***@mlflow.example" in out


def test_log_task_to_mlflow_prints_clean_run_url(tmp_path, capsys):
    client = _PrintingClient()
    settings = Settings(
        repo_root=tmp_path,
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model=None,
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri="https://user:pw123@mlflow.example",
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=False,
        otel_exporter_otlp_endpoint=None,
    )
    run_engine.log_task_to_mlflow(
        client, settings, "all", None, _result(tmp_path)
    )
    out = capsys.readouterr().out
    # shlepa prints its own run link, host only, never the password
    assert "https://mlflow.example/#/experiments/99/runs/r1" in out
    assert "pw123" not in out
    # and whatever the client still prints is masked
    assert "secretpass" not in out


def test_log_task_to_mlflow_file_store(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)
    (tmp_path / "result.json").write_text("{}")

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "stub-model", _result(tmp_path)
    )

    run = client.get_run(run_id)
    assert run.data.metrics["solved"] == 1.0
    assert run.data.metrics["duration_sec"] == 1.25
    assert run.data.metrics["tokens_in"] == 10
    assert run.data.metrics["tokens_out"] == 5
    assert run.data.metrics["tokens_total"] == 15
    assert run.data.metrics["tool_calls"] == 2
    assert run.data.tags["preset"] == "all"
    assert run.data.tags["model"] == "stub-model"
    assert run.data.tags["endpoint_class"] == "main"
    assert "final_output" not in run.data.params
    artifact = client.download_artifacts(run_id, "data/final-output.txt")
    assert Path(artifact).read_text() == "Created hello.txt"
    # Experiment name == task family, run name == task slug.
    assert client.get_experiment(run.info.experiment_id).name == "contest"
    assert run.info.run_name == "contest-hello-file"


def test_log_task_to_mlflow_logs_cache_metrics(tmp_path):
    """Cache metrics are always logged (stable schema; 0 when the
    endpoint doesn't report cache). Issue #71."""
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "quick", None,
        _result(tmp_path, tokens_cache_read=750, tokens_cache_write=30),
    )
    run = client.get_run(run_id)
    assert run.data.metrics["tokens_cache_read"] == 750
    assert run.data.metrics["tokens_cache_write"] == 30

    # legacy result (no cache fields) -> the metrics exist as 0
    run_id0 = run_engine.log_task_to_mlflow(
        client, settings, "quick", None, _result(tmp_path)
    )
    run0 = client.get_run(run_id0)
    assert run0.data.metrics["tokens_cache_read"] == 0
    assert run0.data.metrics["tokens_cache_write"] == 0


def test_log_task_unsolved_metrics(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "quick", None, _result(tmp_path, solved=False)
    )

    run = client.get_run(run_id)
    assert run.data.metrics["solved"] == 0.0
    assert run.data.tags["model"] == "env"
    # Family comes from the slug, not the (arbitrary) preset name.
    assert client.get_experiment(run.info.experiment_id).name == "contest"


def test_log_task_experiment_is_task_family(tmp_path):
    """bench-* slugs land in bench-<x> experiments even under preset 'all'."""
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path, slug="bench-soc-ntds-vss-a")
    )

    run = client.get_run(run_id)
    assert run.data.tags["preset"] == "all"
    assert run.data.tags["model"] == "m"
    assert client.get_experiment(run.info.experiment_id).name == "bench-soc"


def test_log_task_logs_error_param(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client,
        settings,
        "all",
        "m",
        _result(tmp_path, ok=False, solved=False, error="boom"),
    )

    run = client.get_run(run_id)
    assert "error" not in run.data.params
    assert Path(client.download_artifacts(run_id, "data/error.txt")).read_text() == "boom"
    assert run.info.status == "FAILED"
    assert run.data.metrics["solved"] == 0.0


def test_log_task_batch_id_tag(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client,
        settings,
        "all",
        "m",
        _result(tmp_path),
        batch_id="20260827-233000-abcdef",
    )

    run = client.get_run(run_id)
    assert run.data.tags["batch_id"] == "20260827-233000-abcdef"


def test_log_task_without_batch_id_has_no_batch_tag(tmp_path):
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "all", "m", _result(tmp_path)
    )

    run = client.get_run(run_id)
    assert "batch_id" not in run.data.tags
    assert "mlflow_trace_id" not in run.data.tags


# --- Trace lookup (batch -> mlflow_trace_id tag) ---------------------------


class _FakeSpan:
    def __init__(self, name, attributes):
        self.name = name
        self.attributes = attributes


class _FakeTraceData:
    def __init__(self, spans):
        self.spans = spans


class _FakeTraceInfo:
    def __init__(self, trace_id, tags, request_time_ms):
        self.trace_id = trace_id
        self.tags = tags
        self.request_time = request_time_ms


class _FakeTrace:
    def __init__(self, trace_id, tags, request_time_ms, spans):
        self.info = _FakeTraceInfo(trace_id, tags, request_time_ms)
        self.data = _FakeTraceData(spans)


class _FakePagedList(list):
    """List stand-in for mlflow PagedList (it is a list subclass)."""


AGENT_TAG = {"service.name": "shlepa-agent"}


def _agent_trace(trace_id, batch_id, task, request_time_ms=2000):
    return _FakeTrace(
        trace_id,
        dict(AGENT_TAG),
        request_time_ms,
        [
            _FakeSpan("agent.run", {"task": task, "shlepa.batch_id": batch_id}),
            _FakeSpan("chat", {"openinference.span.kind": "LLM"}),
        ],
    )


class _FakeTraceClient:
    def __init__(self, traces):
        self.traces = traces
        self.tags = {}
        self.errors = []
        self.links = []

    def link_traces_to_run(self, trace_ids, run_id):
        self.links.append((run_id, list(trace_ids)))

    def get_experiment_by_name(self, name):
        if name == "shlepa-traces":
            return type("Exp", (), {"experiment_id": "42"})()
        return None

    def search_traces(self, experiment_ids=None, max_results=None, **kwargs):
        return _FakePagedList(self.traces)

    def get_trace(self, trace_id, display=True, flush=False):
        return next(t for t in self.traces if t.info.trace_id == trace_id)

    def set_tag(self, run_id, key, value, synchronous=None):
        self.tags[(run_id, key)] = value


def _otel_settings(tmp_path, experiment="21"):
    base = _settings(tmp_path)
    return Settings(
        **{
            **base.__dict__,
            "shlepa_otel_enabled": True,
            "mlflow_telemetry_experiment_id": experiment,
        }
    )


def test_find_batch_trace_matches_span_attribute():
    client = _FakeTraceClient(
        [
            _agent_trace("tr-other", "batch-1", "other-task"),
            _agent_trace("tr-match", "batch-2", "contest-hello-file"),
        ]
    )
    trace_id = run_engine.find_batch_trace(
        client, _otel_settings(Path(".")), "batch-2", "contest-hello-file"
    )
    assert trace_id == "tr-match"


def test_find_batch_trace_requires_task_match():
    client = _FakeTraceClient(
        [_agent_trace("tr-x", "batch-2", "other-task")]
    )
    assert run_engine.find_batch_trace(
        client, _otel_settings(Path(".")), "batch-2", "contest-hello-file"
    ) is None


def test_find_batch_trace_never_raises_on_broken_client():
    class _BrokenClient(_FakeTraceClient):
        def search_traces(self, *args, **kwargs):
            raise RuntimeError("server exploded")

    client = _BrokenClient([_agent_trace("tr-x", "b", "t")])
    assert run_engine.find_batch_trace(
        client, _otel_settings(Path(".")), "b", "t"
    ) is None


def test_find_batch_trace_tag_level_match_skips_fetch():
    trace = _FakeTrace(
        "tr-tagged",
        {
            "service.name": "shlepa-agent",
            "shlepa.batch_id": "batch-3",
        },
        2000,
        [],  # spans never inspected on the tag path
    )
    client = _FakeTraceClient([trace])

    def boom(trace_id, display=True, flush=False):
        raise AssertionError("get_trace should not be called")

    client.get_trace = boom
    assert run_engine.find_batch_trace(
        client, _otel_settings(Path(".")), "batch-3", "any-task"
    ) == "tr-tagged"


def test_find_batch_trace_ignores_other_services_and_old_traces():
    traces = [
        _FakeTrace("tr-old", dict(AGENT_TAG), 1000,
                   [_FakeSpan("agent.run", {"task": "t", "shlepa.batch_id": "b"})]),
        _FakeTrace("tr-other-svc",
                   {"service.name": "shlepa-doctor"}, 2000,
                   [_FakeSpan("agent.run", {"task": "t", "shlepa.batch_id": "b"})]),
    ]
    client = _FakeTraceClient(traces)
    assert run_engine.find_batch_trace(
        client, _otel_settings(Path(".")), "b", "t", since_ms=1500
    ) is None


class _Run:
    class info:
        run_id = "run-1"


def _install_run_logging(client):
    """Give the fake client the run-logging surface of log_task_to_mlflow."""
    client.create_experiment = lambda name: "42"
    client.create_run = lambda experiment_id, run_name, tags: _Run()
    client.log_metric = lambda *a, **k: None
    client.log_param = lambda *a, **k: None
    client.log_artifact = lambda *a, **k: None
    client.set_terminated = lambda *a, **k: None


def test_log_task_records_trace_tag(tmp_path):
    client = _FakeTraceClient(
        [_agent_trace("tr-match", "batch-2", "contest-hello-file")]
    )
    _install_run_logging(client)
    created_tags = {}

    def create_run(experiment_id, run_name, tags):
        created_tags.update(tags)
        return _Run()

    client.create_run = create_run

    run_id = run_engine.log_task_to_mlflow(
        client,
        _otel_settings(tmp_path),
        "all",
        "m",
        _result(tmp_path),
        batch_id="batch-2",
    )
    assert client.tags.get((run_id, "mlflow_trace_id")) == "tr-match"
    assert created_tags.get("batch_id") == "batch-2"


def test_log_task_links_trace_to_run(tmp_path):
    client = _FakeTraceClient(
        [_agent_trace("tr-match", "batch-2", "contest-hello-file")]
    )
    _install_run_logging(client)

    run_id = run_engine.log_task_to_mlflow(
        client,
        _otel_settings(tmp_path),
        "all",
        "m",
        _result(tmp_path),
        batch_id="batch-2",
    )
    assert client.links == [(run_id, ["tr-match"])]


def test_log_task_link_failure_never_fails_the_run(tmp_path, capsys):
    client = _FakeTraceClient(
        [_agent_trace("tr-match", "batch-2", "contest-hello-file")]
    )
    _install_run_logging(client)

    def boom(*args, **kwargs):
        raise RuntimeError("link endpoint down")

    client.link_traces_to_run = boom

    run_id = run_engine.log_task_to_mlflow(
        client,
        _otel_settings(tmp_path),
        "all",
        "m",
        _result(tmp_path),
        batch_id="batch-2",
    )
    # Run still logged + tagged; the link failure only warns.
    assert run_id == "run-1"
    assert client.tags.get((run_id, "mlflow_trace_id")) == "tr-match"
    assert "link" in capsys.readouterr().out.lower()


def test_log_task_missing_trace_warns_and_still_logs(tmp_path, capsys):
    client = _FakeTraceClient([])
    _install_run_logging(client)

    run_id = run_engine.log_task_to_mlflow(
        client,
        _otel_settings(tmp_path),
        "all",
        "m",
        _result(tmp_path),
        batch_id="batch-2",
        trace_wait_sec=0,
    )
    assert run_id == "run-1"
    assert "mlflow_trace_id" not in [k for (_r, k) in client.tags]
    out = capsys.readouterr().out
    assert "trace" in out.lower()


# --- Dangling-run closing (F5) --------------------------------------------


def _task(root, slug):
    task_dir = root / "tasks" / slug
    (task_dir / "tests").mkdir(parents=True)
    (task_dir / "instruction.md").write_text("Create a file.")
    (task_dir / "tests" / "test_check.py").write_text(
        "import os, pathlib\n\n"
        "def test_f():\n"
        "    ws = pathlib.Path(os.environ['SLEPA_WORKSPACE'])\n"
        "    assert (ws / 'out.txt').read_text() == 'out'\n"
    )
    return Task(slug=slug, name=slug, path=task_dir, timeout_sec=60)


def _ok_runner(instruction, workdir, model, timeout_sec, otel):
    (workdir / "out.txt").write_text("out")
    return run_engine.AgentRun("done", 5, 3, 1)


def _crash_runner(instruction, workdir, model, timeout_sec, otel):
    if "crash" in workdir.name:
        raise RuntimeError("agent crashed")
    return _ok_runner(instruction, workdir, model, timeout_sec, otel)


def test_mid_batch_task_crash_closes_run_failed(tmp_path):
    """A task that crashes mid-batch leaves its MLflow run FAILED (never
    PENDING/RUNNING) with the termination reason; the batch keeps going."""
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'store'}")
    tasks = [_task(tmp_path, "crash-task"), _task(tmp_path, "ok-task")]
    preset = Preset(name="all", tasks="all")
    results = run_engine.run_preset(
        _settings(tmp_path),
        preset,
        tasks,
        model="m",
        no_docker=True,
        agent_runner=_crash_runner,
        mlflow_client=client,
    )
    assert len(results) == 2
    assert not results[0].ok

    crash_runs = client.search_runs(
        [client.get_experiment_by_name("crash").experiment_id]
    )
    assert len(crash_runs) == 1
    assert crash_runs[0].info.status == "FAILED"
    assert "agent crashed" in crash_runs[0].data.tags["termination_reason"]

    # The healthy sibling keeps the normal FINISHED terminal state.
    ok_runs = client.search_runs(
        [client.get_experiment_by_name("ok").experiment_id]
    )
    assert len(ok_runs) == 1
    assert ok_runs[0].info.status == "FINISHED"


class _FailingMetricClient(MlflowClient):
    """MlflowClient whose first log_metric call explodes."""

    def __init__(self, tracking_uri):
        super().__init__(tracking_uri=tracking_uri)
        self._metric_calls = 0

    def log_metric(self, run_id, key, value, **kwargs):
        self._metric_calls += 1
        if self._metric_calls == 1:
            raise RuntimeError("mlflow down")
        return super().log_metric(run_id, key, value, **kwargs)


def test_logging_failure_closes_run_failed(tmp_path):
    """An MLflow failure mid-logging (or an engine interrupt) must not
    leave the run PENDING/RUNNING: the finally closes it as FAILED with
    the failure reason."""
    client = _FailingMetricClient(f"file://{tmp_path / 'store'}")
    tasks = [_task(tmp_path, "ok-task")]
    preset = Preset(name="all", tasks="all")
    with pytest.raises(RuntimeError, match="mlflow down"):
        run_engine.run_preset(
            _settings(tmp_path),
            preset,
            tasks,
            model="m",
            no_docker=True,
            agent_runner=_ok_runner,
            mlflow_client=client,
        )
    runs = client.search_runs(
        [client.get_experiment_by_name("ok").experiment_id]
    )
    assert len(runs) == 1
    assert runs[0].info.status == "FAILED"
    assert "mlflow down" in runs[0].data.tags["termination_reason"]


def test_post_batch_sweep_closes_orphaned_runs(tmp_path):
    """The post-batch sweep marks leftover batch-tagged open runs FAILED
    and leaves already-finished runs untouched."""
    client = MlflowClient(tracking_uri=f"file://{tmp_path / 'store'}")
    batch = "20260902-120000-abc123"
    orphan_exp_id = client.create_experiment("orphan-fam")
    orphan = client.create_run(
        experiment_id=orphan_exp_id, run_name="orphan", tags={"batch_id": batch}
    )
    # Left RUNNING on purpose: the sweep must close it.
    done_exp_id = client.create_experiment("done-fam")
    done = client.create_run(
        experiment_id=done_exp_id, run_name="done", tags={"batch_id": batch}
    )
    client.set_terminated(done.info.run_id, status="FINISHED")

    closed = run_engine.sweep_orphaned_batch_runs(client, batch)

    assert closed == [orphan.info.run_id]
    assert client.get_run(orphan.info.run_id).info.status == "FAILED"
    assert (
        "orphaned" in client.get_run(orphan.info.run_id).data.tags[
            "termination_reason"
        ]
    )
    assert client.get_run(done.info.run_id).info.status == "FINISHED"
    assert "termination_reason" not in client.get_run(done.info.run_id).data.tags


def test_post_batch_sweep_never_raises():
    class _Boom:
        def search_experiments(self):
            raise RuntimeError("store exploded")

    assert run_engine.sweep_orphaned_batch_runs(_Boom(), "b") == []
    assert run_engine.sweep_orphaned_batch_runs(_Boom(), None) == []


def test_log_task_to_mlflow_logs_per_phase_metrics(tmp_path):
    """Per-phase metrics are logged for every phase present in the event
    stream and for no others; per-phase tokens_in sums to the total.
    Issue #73."""
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client,
        settings,
        "quick",
        None,
        _result(
            tmp_path,
            phase_tokens={
                "plan": {"in": 6, "out": 3, "cache_read": 2},
                "work": {"in": 4, "out": 2, "cache_read": 1},
            },
        ),
    )
    m = client.get_run(run_id).data.metrics
    assert m["tokens_in.plan"] == 6
    assert m["tokens_out.plan"] == 3
    assert m["tokens_cache_read.plan"] == 2
    assert m["tokens_in.work"] == 4
    assert m["tokens_out.work"] == 2
    assert m["tokens_cache_read.work"] == 1
    # phases that did not run produce no entries at all
    per_phase = {k for k in m if "." in k}
    assert per_phase == {
        "tokens_in.plan", "tokens_out.plan", "tokens_cache_read.plan",
        "tokens_in.work", "tokens_out.work", "tokens_cache_read.work",
    }
    # consistency: per-phase tokens_in sums to the total tokens_in
    assert m["tokens_in.plan"] + m["tokens_in.work"] == m["tokens_in"]


def test_log_task_to_mlflow_legacy_result_has_no_per_phase_metrics(tmp_path):
    """Results without phase data log no dotted metrics (legacy runs keep
    their metric shape). Issue #73."""
    tracking_uri = f"file://{tmp_path / 'mlstore'}"
    client = MlflowClient(tracking_uri=tracking_uri)
    settings = _settings(tmp_path)

    run_id = run_engine.log_task_to_mlflow(
        client, settings, "quick", None, _result(tmp_path)
    )
    m = client.get_run(run_id).data.metrics
    assert not any("." in k for k in m)
