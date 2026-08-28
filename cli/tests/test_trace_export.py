"""Tests for the MLflow trace batch exporter (trace_export).

Pure-function core: the MlflowClient is injected as a fake, no server.
"""

import json

import pytest

from shlepa_cli import trace_export
from shlepa_cli.config import Settings


def _settings(**overrides):
    base = dict(
        repo_root=".",
        openai_base_url=None,
        openai_api_key=None,
        local_agent_model="m",
        ci_openai_base_url=None,
        ci_openai_api_key=None,
        ci_model=None,
        mlflow_tracking_uri=None,
        mlflow_tracking_username=None,
        mlflow_tracking_password=None,
        shlepa_otel_enabled=True,
        otel_exporter_otlp_endpoint=None,
        mlflow_telemetry_experiment_id="21",
    )
    base.update(overrides)
    return Settings(**base)


class _Span:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Info:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Trace:
    def __init__(self, trace_id, spans=(), tags=None, state="OK",
                 request_time=1000):
        self.info = _Info(
            trace_id=trace_id,
            tags=tags or {},
            state=state,
            request_time=request_time,
        )
        self.data = type("Data", (), {"spans": list(spans)})()


def _agent_span(batch_id, task="contest-hello-file", extra=None):
    attrs = {
        "shlepa.batch_id": batch_id,
        "task": task,
    }
    if extra:
        attrs.update(extra)
    return _Span(
        span_id="span-1",
        parent_id=None,
        name="agent.run",
        span_type="AGENT",
        model_name=None,
        status="OK",
        start_time_ns=1,
        end_time_ns=2,
        attributes=attrs,
        events=[type("Event", (), {})()],
        inputs=None,
        outputs=None,
    )


def _llm_span(batch_id, task="contest-hello-file"):
    return _Span(
        span_id="span-2",
        parent_id="span-1",
        name="LLM Qwen",
        span_type="LLM",
        model_name="Qwen3.8",
        status="OK",
        start_time_ns=2,
        end_time_ns=3,
        attributes={
            "shlepa.batch_id": batch_id,
            "task": task,
            "llm.token_count.prompt": "5",
            "llm.token_count.completion": "3",
        },
        events=[],
        inputs={"messages": [{"role": "user", "content": "hi"}]},
        outputs={"content": "hello.txt created"},
    )


class _PagedList(list):
    """List stand-in for mlflow PagedList (a list subclass)."""


class _FakeClient:
    def __init__(self, traces):
        self.traces = traces
        self.search_kwargs: list[dict] = []

    def get_experiment_by_name(self, name):
        return type("Exp", (), {"experiment_id": "42"})()

    def search_traces(self, **kwargs):
        self.search_kwargs.append(kwargs)
        return _PagedList(self.traces)

    def get_trace(self, trace_id):
        return next(t for t in self.traces if t.info.trace_id == trace_id)


def test_find_batch_traces_filters_by_service_and_batch():
    client = _FakeClient(
        [
            _Trace("tr-a", [_agent_span("batch-1")],
                   tags={"service.name": "shlepa-agent"}),
            # Same batch but the doctor's probe service: excluded.
            _Trace("tr-probe", [_agent_span("batch-1")],
                   tags={"service.name": "shlepa-doctor"}),
            # Agent service but a different batch (span-level tag).
            _Trace("tr-other", [_agent_span("batch-9")],
                   tags={"service.name": "shlepa-agent"}),
        ]
    )
    found = trace_export.find_batch_traces(
        client, _settings(), "batch-1"
    )
    assert [t.info.trace_id for t in found] == ["tr-a"]
    # The search must be by experiment id (the locations= query form
    # hangs on the current MLflow server). The numeric settings id is
    # used as-is.
    kwargs = client.search_kwargs[0]
    assert kwargs["experiment_ids"] == ["21"]
    assert "locations" not in kwargs


def test_find_batch_traces_empty_when_experiment_unknown():
    class _NoExp(_FakeClient):
        def get_experiment_by_name(self, name):
            return None

    client = _NoExp([_Trace("tr-a", [_agent_span("b")])])
    # No numeric id in settings -> resolve by name -> unknown -> no search.
    found = trace_export.find_batch_traces(
        client, _settings(mlflow_telemetry_experiment_id=None), "batch-1"
    )
    assert found == []
    assert client.search_kwargs == []


def test_find_batch_traces_never_raises_on_broken_client():
    class _Broken(_FakeClient):
        def search_traces(self, **kwargs):
            raise RuntimeError("server exploded")

    assert trace_export.find_batch_traces(
        _Broken([]), _settings(), "batch-1"
    ) == []


def test_trace_to_dict_round_trips_a_synthetic_trace():
    trace = _Trace(
        "tr-x",
        [_agent_span("batch-1"), _llm_span("batch-1")],
        tags={"service.name": "shlepa-agent"},
    )
    data = trace_export.trace_to_dict(trace)
    # Stable JSON: serializes without loss for analysis.
    parsed = json.loads(json.dumps(data))
    assert parsed["trace_id"] == "tr-x"
    assert parsed["task"] == "contest-hello-file"
    assert parsed["state"] == "OK"
    assert len(parsed["spans"]) == 2
    root = parsed["spans"][0]
    assert root["name"] == "agent.run"
    assert root["span_id"] == "span-1"
    assert root["parent_id"] is None
    assert root["attributes"]["shlepa.batch_id"] == "batch-1"
    llm = parsed["spans"][1]
    assert llm["parent_id"] == "span-1"
    assert llm["span_type"] == "LLM"
    assert llm["model_name"] == "Qwen3.8"
    assert llm["attributes"]["llm.token_count.prompt"] == "5"
    assert llm["inputs"]["messages"][0]["role"] == "user"
    assert llm["outputs"]["content"] == "hello.txt created"


def test_trace_to_dict_handles_missing_pieces():
    trace = _Trace(
        "tr-bare",
        [_Span(name="x")],
        tags=None,
    )
    data = trace_export.trace_to_dict(trace)
    assert data["trace_id"] == "tr-bare"
    assert data["task"] is None
    assert data["spans"][0]["attributes"] == {}
    json.dumps(data)  # still JSON-stable


# --- export_batch: files on disk ---------------------------------------


class _TraceWithTask(_Trace):
    """_Trace whose agent span also carries the task attribute."""


def _llm_span_dict(prompt, completion, i=0):
    return _Span(
        span_id=f"llm-{i}",
        parent_id=None,
        name="LLM turn",
        span_type="LLM",
        model_name="Qwen",
        status="OK",
        start_time_ns=i * 1_000_000_000,
        end_time_ns=(i + 1) * 1_000_000_000,
        attributes={
            "llm.token_count.prompt": str(prompt),
            "llm.token_count.completion": str(completion),
        },
        events=[],
        inputs=None,
        outputs=None,
    )


def _llm_span_no_usage():
    return _Span(
        span_id="llm-0",
        parent_id=None,
        name="chat Qwen",
        span_type="LLM",
        model_name="Qwen",
        status="OK",
        start_time_ns=0,
        end_time_ns=1_000_000_000,
        attributes={"gen_ai.operation.name": "chat"},
        events=[],
        inputs=None,
        outputs=None,
    )


def test_manifest_carries_tokens_missing_signal(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-nt",
                [_agent_span("batch-2", "task-a"), _llm_span_no_usage()],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-2", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert "tokens_missing" in line["signals"]


def test_export_batch_raises_when_batch_has_no_traces():
    client = _FakeClient(
        [
            _Trace("tr-other", [_agent_span("batch-9")],
                   tags={"service.name": "shlepa-agent"})
        ]
    )
    with pytest.raises(trace_export.TraceBatchNotFound):
        trace_export.export_batch(client, _settings(), "batch-1", ".")


def test_export_batch_writes_manifest_traces_and_digests(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-a",
                [_agent_span("batch-1", "task-a"),
                 _llm_span_dict(100, 10)],
                tags={"service.name": "shlepa-agent"},
            ),
            _Trace(
                "tr-b",
                [_agent_span("batch-1", "task-b")],
                tags={"service.name": "shlepa-agent"},
            ),
        ]
    )
    out = tmp_path / "export"
    summary = trace_export.export_batch(
        client, _settings(), "batch-1", out
    )
    manifest = (out / "manifest.jsonl").read_text().strip().splitlines()
    assert len(manifest) == 2
    lines = [json.loads(line) for line in manifest]
    by_task = {line["task"]: line for line in lines}
    assert set(by_task) == {"task-a", "task-b"}
    assert by_task["task-a"]["trace_id"] == "tr-a"
    assert by_task["task-a"]["tokens_in"] == 100
    trace_a = json.loads((out / "traces" / "task-a.json").read_text())
    assert trace_a["trace_id"] == "tr-a"
    assert (out / "digests" / "task-a.md").read_text().count(
        "Trace digest"
    ) == 1
    summary_md = (out / "summary.md").read_text()
    assert "batch-1" in summary_md
    assert summary["batch_id"] == "batch-1"
    assert summary["traces"] == 2


# --- CLI command -------------------------------------------------------


def test_trace_export_cli_empty_batch_nonzero_exit(
    tmp_path, monkeypatch
):
    from typer.testing import CliRunner

    from shlepa_cli import main as cli_main
    from shlepa_cli import mlflow_client as mlflow_module

    monkeypatch.setattr(
        mlflow_module, "get_mlflow_client", lambda s: _FakeClient([])
    )
    result = CliRunner().invoke(
        cli_main.app,
        [
            "trace-export",
            "--batch",
            "no-such-batch",
            "--out",
            str(tmp_path / "out"),
        ],
    )
    assert result.exit_code != 0
    assert "no-such-batch" in (result.output + str(result.exception))


def test_trace_export_cli_writes_batch_files(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from shlepa_cli import main as cli_main
    from shlepa_cli import mlflow_client as mlflow_module

    client = _FakeClient(
        [
            _Trace(
                "tr-a",
                [_agent_span("batch-7", "task-a")],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    monkeypatch.setattr(
        mlflow_module, "get_mlflow_client", lambda s: client
    )
    out = tmp_path / "out"
    result = CliRunner().invoke(
        cli_main.app,
        ["trace-export", "--batch", "batch-7", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert (out / "manifest.jsonl").is_file()
    assert (out / "traces" / "task-a.json").is_file()
    assert (out / "summary.md").is_file()
