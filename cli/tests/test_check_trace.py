"""Tests for otel/check_trace.py (Jaeger trace verification).

The script is a standalone dev tool in otel/; tests load it by file path.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_check_trace():
    spec = importlib.util.spec_from_file_location(
        "check_trace", REPO_ROOT / "otel" / "check_trace.py"
    )
    module = importlib.util.module_from_spec(spec)
    # dataclass processing resolves cls.__module__ via sys.modules
    sys.modules["check_trace"] = module
    spec.loader.exec_module(module)
    return module


check_trace = _load_check_trace()


def _tag(key, value):
    return {"key": key, "type": "string", "value": value}


def _llm_span(with_tokens: bool = True) -> dict:
    tags = [_tag("openinference.span.kind", "LLM")]
    if with_tokens:
        tags.append({"key": "gen_ai.usage.input_tokens", "type": "int", "value": 120})
        tags.append({"key": "gen_ai.usage.output_tokens", "type": "int", "value": 40})
    return {
        "traceID": "abc123",
        "spanID": "s2",
        "operationName": "chat",
        "startTime": 1_700_000_000_001_000,
        "duration": 4_000,
        "tags": tags,
        "processID": "p1",
    }


def _root_span(with_task: bool = True) -> dict:
    tags = [_tag("task", "contest-hello-file")] if with_task else []
    return {
        "traceID": "abc123",
        "spanID": "s1",
        "operationName": "agent.run",
        "startTime": 1_700_000_000_000_000,
        "duration": 5_000,
        "tags": tags,
        "processID": "p1",
    }


def _trace(trace_id: str = "abc123", spans=None) -> dict:
    if spans is None:
        spans = [_root_span(), _llm_span()]
    return {
        "traceID": trace_id,
        "spans": spans,
        "processes": {"p1": {"serviceName": "shlepa-agent"}},
    }


def test_latest_trace_picks_most_recent_end_time():
    payload = {
        "data": [
            _trace("older"),  # end 1_700_000_000_005_000
            _trace("newer"),
        ]
    }
    # make the second trace end later
    for span in payload["data"][1]["spans"]:
        span["startTime"] += 10_000
    latest = check_trace.latest_trace(payload)
    assert latest is not None
    assert latest["traceID"] == "newer"


def test_latest_trace_empty_payload():
    assert check_trace.latest_trace({"data": []}) is None
    assert check_trace.latest_trace({}) is None


def test_check_trace_ok():
    result = check_trace.check_trace(_trace())
    assert result.ok, result.detail
    assert result.trace_id == "abc123"


def test_check_trace_no_llm_span():
    result = check_trace.check_trace(_trace(spans=[_root_span()]))
    assert not result.ok
    assert "llm" in result.detail.lower()


def test_check_trace_llm_without_token_usage():
    result = check_trace.check_trace(_trace(spans=[_root_span(), _llm_span(with_tokens=False)]))
    assert not result.ok
    assert "token" in result.detail.lower()


def test_check_trace_missing_task_attribute():
    result = check_trace.check_trace(_trace(spans=[_root_span(with_task=False), _llm_span()]))
    assert not result.ok
    assert "task" in result.detail.lower()


def test_fetch_latest_trace_uses_jaeger_api(monkeypatch):
    payload = {"data": [_trace()]}
    body = io.BytesIO(json.dumps(payload).encode("utf-8"))

    class _FakeResponse:
        def __enter__(self):
            return body

        def __exit__(self, *args):
            return False

    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr(
        check_trace.urllib.request, "urlopen", fake_urlopen
    )

    trace = check_trace.fetch_latest_trace("http://jaeger:16686", "shlepa-agent")
    assert trace is not None
    assert trace["traceID"] == "abc123"
    assert "service=shlepa-agent" in captured["url"]
    assert captured["url"].startswith("http://jaeger:16686/api/traces?")
