"""Tests for the MLflow trace batch exporter (trace_export).

Pure-function core: the MlflowClient is injected as a fake, no server.
"""

import json

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
