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


def _phase_agent_span(name, i=0, input_tokens=0, output_tokens=0,
                      cache_read=0):
    """An invoke_agent span carrying aggregated per-phase usage.

    Mirrors pydantic-ai's agent-run spans: name 'invoke_agent <agent>',
    gen_ai.aggregated_usage.* attributes (absent when zero).
    """
    attrs = {
        "agent_name": name,
        "gen_ai.agent.name": name,
        "gen_ai.operation.name": "invoke_agent",
    }
    if input_tokens:
        attrs["gen_ai.aggregated_usage.input_tokens"] = str(input_tokens)
    if output_tokens:
        attrs["gen_ai.aggregated_usage.output_tokens"] = str(output_tokens)
    if cache_read:
        attrs["gen_ai.aggregated_usage.cache_read.input_tokens"] = str(cache_read)
    return _Span(
        span_id=f"agent-{i}",
        parent_id=None,
        name=f"invoke_agent {name}",
        span_type="AGENT",
        model_name="Qwen",
        status="OK",
        start_time_ns=i * 10 * 1_000_000_000,
        end_time_ns=(i + 1) * 10 * 1_000_000_000,
        attributes=attrs,
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


def test_export_batch_applies_since_window(tmp_path):
    # batch id 20260828-000000-abc123 -> batch start 2026-08-28 00:00:00Z
    batch_start_ms = 1_787_875_200_000
    old = _Trace(
        "tr-old",
        [_agent_span("20260828-000000-abc123", "task-a")],
        tags={"service.name": "shlepa-agent"},
        request_time=batch_start_ms - 30 * 86_400_000,
    )
    fresh = _Trace(
        "tr-fresh",
        [_agent_span("20260828-000000-abc123", "task-a")],
        tags={"service.name": "shlepa-agent"},
        request_time=batch_start_ms + 1_000,
    )
    client = _FakeClient([old, fresh])
    out = tmp_path / "e"
    trace_export.export_batch(
        client, _settings(), "20260828-000000-abc123", out
    )
    lines = (out / "manifest.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    assert "tr-fresh" in lines[0]


def test_batch_since_ms_parsing():
    # 2026-08-28 00:00:00Z - 5min margin
    assert trace_export._batch_since_ms(
        "20260828-000000-abc123"
    ) == 1_787_875_200_000 - 300_000
    assert trace_export._batch_since_ms("ad-hoc") is None
    assert trace_export._batch_since_ms("20261399-000000-abc123") is None


def test_export_batch_tolerates_ad_hoc_batch_id(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-x",
                [_agent_span("ad-hoc", "task-a")],
                tags={"service.name": "shlepa-agent"},
                request_time=0,
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "ad-hoc", out)
    lines = (out / "manifest.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1


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


def _llm_span_with_cache(cache_read):
    return _Span(
        span_id="llm-cache",
        parent_id=None,
        name="chat model",
        span_type="LLM",
        model_name="Qwen",
        status="OK",
        start_time_ns=0,
        end_time_ns=1_000_000_000,
        attributes={
            "gen_ai.usage.input_tokens": "1000",
            "gen_ai.usage.output_tokens": "50",
            "gen_ai.usage.cache_read.input_tokens": str(cache_read),
        },
        events=[],
        inputs=None,
        outputs=None,
    )


def test_manifest_carries_tokens_cache_read_when_reported(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-c",
                [_agent_span("batch-c", "task-a"), _llm_span_with_cache(750)],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-c", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert line["tokens_cache_read"] == 750


def test_manifest_no_cache_field_for_legacy_traces(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-l",
                [_agent_span("batch-l", "task-a"),
                 _llm_span("batch-l", "task-a")],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-l", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert "tokens_cache_read" not in line


def _llm_span_with_output_messages(parts):
    return _Span(
        span_id="llm-msg",
        parent_id=None,
        name="chat model",
        span_type="LLM",
        model_name="Qwen",
        status="OK",
        start_time_ns=0,
        end_time_ns=1_000_000_000,
        attributes={
            "gen_ai.usage.input_tokens": "10",
            "gen_ai.usage.output_tokens": "2",
            # OTLP-side shape: a JSON string of typed parts.
            "gen_ai.output.messages": json.dumps(
                [{"role": "assistant", "parts": parts}]
            ),
        },
        events=[],
        inputs=None,
        outputs=None,
    )


def test_manifest_carries_no_thinking_and_digest_count(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-think",
                [
                    _agent_span("batch-t", "task-think"),
                    _llm_span_with_output_messages(
                        [{"type": "thinking", "content": "think"}]
                    ),
                ],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-t", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert "no_thinking" not in line["signals"]
    assert "messages_missing" not in line["signals"]
    digest = (out / "digests" / "task-think.md").read_text()
    assert "thinking_parts: 1" in digest


def test_manifest_carries_no_thinking_when_messages_present(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-nothink",
                [
                    _agent_span("batch-nt", "task-nt"),
                    _llm_span_with_output_messages(
                        [{"type": "text", "content": "answer"}]
                    ),
                ],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-nt", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert "no_thinking" in line["signals"]
    assert "messages_missing" not in line["signals"]
    digest = (out / "digests" / "task-nt.md").read_text()
    assert "thinking_parts: 0" in digest


def test_manifest_carries_messages_missing_when_no_messages(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-miss",
                [
                    _agent_span("batch-m", "task-m"),
                    _llm_span_with_output_messages(
                        [{"type": "text", "content": "a"}]
                    ),
                ],
                tags={"service.name": "shlepa-agent"},
            ),
            _Trace(
                "tr-miss2",
                [
                    _agent_span("batch-m", "task-m2"),
                    _llm_span_no_usage(),  # no usage, no messages
                ],
                tags={"service.name": "shlepa-agent"},
            ),
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-m", out)
    lines = {
        json.loads(line)["task"]: json.loads(line)
        for line in (out / "manifest.jsonl")
        .read_text()
        .strip()
        .splitlines()
    }
    m2 = lines["task-m2"]
    assert "messages_missing" in m2["signals"]
    assert "no_thinking" not in m2["signals"]
    digest = (out / "digests" / "task-m2.md").read_text()
    assert "thinking_parts: n/a" in digest


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


# --- per-phase token table (issue #73) ---------------------------------


def test_phase_tokens_parsed_from_phase_agent_spans():
    from shlepa_cli import trace_digest

    data = {
        "trace_id": "tr-ph",
        "task": "task-ph",
        "spans": trace_export.trace_to_dict(
                _Trace(
                    "tr-ph",
                    [
                        _phase_agent_span("plan", 0, 120, 30, 100),
                        _phase_agent_span("work", 1, 800, 200, 500),
                    ],
                )
            )["spans"],
    }
    assert trace_digest.trace_phase_tokens(data) == {
        "plan": {"in": 120, "out": 30, "cache_read": 100},
        "work": {"in": 800, "out": 200, "cache_read": 500},
    }


def test_phase_tokens_sums_spans_of_the_same_phase():
    from shlepa_cli import trace_digest

    # A retried plan phase runs again: both invoke_agent spans belong
    # to the same phase and their usage must be summed.
    data = {
        "trace_id": "tr-ph2",
        "task": "task-ph2",
        "spans": trace_export.trace_to_dict(
                _Trace(
                    "tr-ph2",
                    [
                        _phase_agent_span("plan", 0, 100, 10),
                        _phase_agent_span("plan", 1, 50, 5),
                        _phase_agent_span("work", 2, 700, 90),
                    ],
                )
            )["spans"],
    }
    assert trace_digest.trace_phase_tokens(data) == {
        "plan": {"in": 150, "out": 15, "cache_read": 0},
        "work": {"in": 700, "out": 90, "cache_read": 0},
    }


def test_phase_tokens_empty_for_legacy_traces():
    from shlepa_cli import trace_digest

    # Legacy agent runs used the default agent name 'agent': no phase
    # attribution is possible, so no table is emitted.
    data = {
        "trace_id": "tr-leg",
        "task": "task-leg",
        "spans": trace_export.trace_to_dict(
                _Trace(
                    "tr-leg",
                    [
                        _phase_agent_span("agent", 0, 900, 230),
                        _llm_span_dict(900, 230),
                    ],
                )
            )["spans"],
    }
    assert trace_digest.trace_phase_tokens(data) == {}


def test_digest_includes_phase_token_table():
    from shlepa_cli import trace_digest

    data = {
        "trace_id": "tr-dig",
        "task": "task-dig",
        "state": "OK",
        "spans": trace_export.trace_to_dict(
                _Trace(
                    "tr-dig",
                    [
                        _phase_agent_span("plan", 0, 120, 30, 100),
                        _phase_agent_span("work", 1, 800, 200, 500),
                        _llm_span_dict(120, 30, 0),
                        _llm_span_dict(800, 200, 1),
                    ],
                )
            )["spans"],
    }
    digest = trace_digest.build_digest(data)
    assert "plan: 120 in / 30 out / 100 cache read" in digest
    assert "work: 800 in / 200 out / 500 cache read" in digest
    # The run totals line stays the sum over LLM spans, untouched.
    assert "- tokens: 920 in / 230 out" in digest


def test_digest_has_no_phase_table_for_legacy_trace():
    from shlepa_cli import trace_digest

    data = {
        "trace_id": "tr-leg2",
        "task": "task-leg2",
        "state": "OK",
        "spans": trace_export.trace_to_dict(
                _Trace(
                    "tr-leg2",
                    [
                        _phase_agent_span("agent", 0, 900, 230),
                        _llm_span_dict(900, 230),
                    ],
                )
            )["spans"],
    }
    digest = trace_digest.build_digest(data)
    assert "- phase tokens:" not in digest
    assert "- tokens: 900 in / 230 out" in digest


def test_manifest_carries_phase_tokens(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-mph",
                [
                    _agent_span("batch-p", "task-p"),
                    _phase_agent_span("plan", 0, 120, 30, 100),
                    _phase_agent_span("work", 1, 800, 200, 500),
                ],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-p", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert line["phase_tokens"] == {
        "plan": {"in": 120, "out": 30, "cache_read": 100},
        "work": {"in": 800, "out": 200, "cache_read": 500},
    }


def test_manifest_no_phase_tokens_for_legacy_traces(tmp_path):
    client = _FakeClient(
        [
            _Trace(
                "tr-leg3",
                [
                    _agent_span("batch-l3", "task-l3"),
                    _phase_agent_span("agent", 0, 900, 230),
                ],
                tags={"service.name": "shlepa-agent"},
            )
        ]
    )
    out = tmp_path / "e"
    trace_export.export_batch(client, _settings(), "batch-l3", out)
    line = json.loads((out / "manifest.jsonl").read_text())
    assert "phase_tokens" not in line


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
