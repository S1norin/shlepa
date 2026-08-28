"""Export agent traces from the MLflow trace experiment as stable JSON.

The run engine tags each MLflow run with ``batch_id`` (and, when the
trace is found, ``mlflow_trace_id``); this module goes the other way:
given a batch id, fetch the traces the agent shipped for that batch and
serialize them into a JSON shape suitable for on-disk dumps and for the
LLM-readable manifest/digests (see ``shlepa traces``).

Search uses ``search_traces(experiment_ids=...)`` deliberately: the
newer ``locations=`` query form hangs on the current MLflow server
(3.15.x), so the deprecated-but-working filter is used.

The core is a pure function: the MlflowClient is injected, so unit
tests need no server.
"""

from __future__ import annotations

from shlepa_cli.run_engine import (
    AGENT_SERVICE,
    _resolve_trace_experiment_id,
)

__all__ = ["find_batch_traces", "trace_to_dict"]


def _spans(trace) -> list:
    return getattr(getattr(trace, "data", None), "spans", None) or []


def find_batch_traces(client, settings, batch_id: str, limit: int = 200):
    """Return the raw Trace objects of one batch in the trace experiment.

    Candidate filtering: trace-level service.name tag, then a
    shlepa.batch_id match at trace-tag level (fast path) or span level.
    Never raises: any client/server problem yields an empty list.
    """
    try:
        exp_id = _resolve_trace_experiment_id(client, settings)
        if exp_id is None:
            return []
        return _find_batch_traces_inner(
            client, exp_id, batch_id, limit
        )
    except Exception:  # noqa: BLE001 - export must not crash the caller
        return []


def _find_batch_traces_inner(
    client, exp_id: str, batch_id: str, limit: int
) -> list:
    found: list = []
    for trace in client.search_traces(
        experiment_ids=[exp_id], max_results=limit
    ):
        info = trace.info
        tags = getattr(info, "tags", None) or {}
        if tags.get("service.name") != AGENT_SERVICE:
            continue
        if tags.get("shlepa.batch_id") == batch_id:
            found.append(trace)
            continue
        attrs = [
            dict(getattr(span, "attributes", None) or {})
            for span in _spans(trace)
        ]
        if any(a.get("shlepa.batch_id") == batch_id for a in attrs):
            found.append(trace)
    return found


def _jsonable(value):
    """Coerce a span field into a JSON-stable value (best effort)."""
    if value is None or isinstance(value, (str, int, float, bool, list, dict)):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return repr(value)


def _event_dict(event) -> dict:
    data = {
        "name": _jsonable(getattr(event, "name", None)),
        "timestamp_ns": _jsonable(getattr(event, "timestamp_ns", None)),
        "attributes": dict(getattr(event, "attributes", None) or {}),
    }
    return data


def _span_dict(span) -> dict:
    data = {
        "span_id": _jsonable(getattr(span, "span_id", None)),
        "parent_id": _jsonable(getattr(span, "parent_id", None)),
        "name": _jsonable(getattr(span, "name", None)),
        "span_type": _jsonable(getattr(span, "span_type", None)),
        "model_name": _jsonable(getattr(span, "model_name", None)),
        "status": _jsonable(getattr(span, "status", None)),
        "start_time_ns": _jsonable(getattr(span, "start_time_ns", None)),
        "end_time_ns": _jsonable(getattr(span, "end_time_ns", None)),
        "attributes": dict(getattr(span, "attributes", None) or {}),
        "events": [
            _event_dict(event)
            for event in (getattr(span, "events", None) or [])
        ],
        "inputs": _jsonable(getattr(span, "inputs", None)),
        "outputs": _jsonable(getattr(span, "outputs", None)),
    }
    return data


def trace_to_dict(trace) -> dict:
    """Serialize one Trace (or a structural stand-in) to a stable dict.

    Output keys: trace_id, task, state, request_time, tags, spans.
    ``task`` is taken from the first span's ``task`` attribute (the
    agent stamps it on every span).
    """
    info = trace.info
    spans = _spans(trace)
    task = None
    for span in spans:
        attrs = getattr(span, "attributes", None) or {}
        if attrs.get("task"):
            task = attrs["task"]
            break
    return {
        "trace_id": getattr(info, "trace_id", None),
        "task": task,
        "state": _jsonable(getattr(info, "state", None)),
        "request_time": _jsonable(getattr(info, "request_time", None)),
        "tags": dict(getattr(info, "tags", None) or {}),
        "spans": [_span_dict(span) for span in spans],
    }
