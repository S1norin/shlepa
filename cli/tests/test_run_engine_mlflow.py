"""Run engine tests: MLflow run logging (file:// store)."""

from pathlib import Path

import pytest

from mlflow import MlflowClient

from shlepa_cli import run_engine
from shlepa_cli.config import Settings


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

    def log_param(self, *args, **kwargs):
        pass

    def set_terminated(self, *args, **kwargs):
        pass


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
    assert run.data.params["final_output"] == "Created hello.txt"
    # Experiment name == task family, run name == task slug.
    assert client.get_experiment(run.info.experiment_id).name == "contest"
    assert run.info.run_name == "contest-hello-file"


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
    assert run.data.params["error"] == "boom"
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
