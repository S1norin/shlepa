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

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from shlepa_cli import mlflow_compat as compat
from shlepa_cli import trace_digest
from shlepa_cli.run_engine import AGENT_SERVICE, DEFAULT_TRACE_EXPERIMENT

__all__ = [
    "TraceBatchNotFound",
    "export_batch",
    "find_batch_traces",
    "trace_to_dict",
]


class TraceBatchNotFound(Exception):
    """No agent traces found for a batch in the trace experiment."""

    def __init__(self, batch_id: str, experiment):
        super().__init__(
            f"no agent traces found for batch {batch_id!r} in experiment "
            f"{experiment!r}; the batch may be too recent (async export) "
            f"or ran with otel disabled"
        )
        self.batch_id = batch_id


def _spans(trace) -> list:
    return getattr(getattr(trace, "data", None), "spans", None) or []


# Batch ids embed their UTC start time: YYYYMMDD-HHMMSS-<6 hex>.
_BATCH_ID_RE = re.compile(r"(\d{8})-(\d{6})-[0-9a-f]{6}")


def _batch_since_ms(batch_id: str, margin_min: int = 5) -> int | None:
    """Batch start (embedded in the batch id) minus a safety margin, ms.

    None for ids not in the generated format (ad-hoc ids): the export
    then falls back to the unfiltered search.
    """
    m = _BATCH_ID_RE.fullmatch(batch_id)
    if m is None:
        return None
    date = m.group(1)
    clock = m.group(2)
    try:
        start = datetime(
            int(date[0:4]), int(date[4:6]), int(date[6:8]),
            int(clock[0:2]), int(clock[2:4]), int(clock[4:6]),
            tzinfo=timezone.utc,
        )
    except ValueError:  # e.g. month 13
        return None
    return int(start.timestamp() * 1000) - margin_min * 60_000


def _experiment_id(client, value: str) -> str | None:
    if value.isdigit():
        return value
    experiment = client.get_experiment_by_name(value)
    return experiment.experiment_id if experiment is not None else None


def _batch_experiment_ids(client, settings, batch_id: str) -> list[str]:
    """Find family experiments containing runs from this batch.

    The legacy configured/static trace experiment remains a fallback so old
    batches keep exporting after new traces move beside their runs.
    """
    found: list[str] = []
    for experiment in client.search_experiments():
        runs = client.search_runs(
            [experiment.experiment_id],
            filter_string=f"tags.batch_id = '{batch_id}'",
            max_results=1,
        )
        if runs:
            found.append(experiment.experiment_id)
    legacy = settings.mlflow_telemetry_experiment_id or DEFAULT_TRACE_EXPERIMENT
    legacy_id = _experiment_id(client, legacy)
    if legacy_id is not None and legacy_id not in found:
        found.append(legacy_id)
    return found


def find_batch_traces(
    client,
    settings,
    batch_id: str,
    limit: int = 500,
    experiment: str | None = None,
):
    """Return raw Trace objects from the batch's family experiments.

    Candidate filtering: trace-level service.name tag, an age window
    derived from the batch id's embedded timestamp, then a
    shlepa.batch_id match at trace-tag level (fast path) or span level.
    Never raises: any client/server problem yields an empty list.
    """
    try:
        if experiment is not None:
            exp_id = _experiment_id(client, experiment)
            experiment_ids = [exp_id] if exp_id is not None else []
        else:
            experiment_ids = _batch_experiment_ids(client, settings, batch_id)
        found: list = []
        for exp_id in experiment_ids:
            found.extend(
                _find_batch_traces_inner(
                    client, exp_id, batch_id, _batch_since_ms(batch_id), limit
                )
            )
        return found
    except Exception:  # noqa: BLE001 - export must not crash the caller
        return []


def _find_batch_traces_inner(
    client,
    exp_id: str,
    batch_id: str,
    since_ms: int | None,
    limit: int,
) -> list:
    found: list = []
    paged = compat.search_experiment_traces(client, exp_id, limit)
    for trace in paged:
        info = trace.info
        tags = getattr(info, "tags", None) or {}
        if tags.get("service.name") != AGENT_SERVICE:
            continue
        if since_ms is not None and (
            getattr(info, "request_time", None) or 0
        ) < since_ms:
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


def _trace_tokens(trace: dict) -> tuple[int, int, int]:
    spans = [s for s in trace.get("spans") or [] if s.get("span_type") == "LLM"]
    return (
        sum(trace_digest.span_prompt_tokens(s) for s in spans),
        sum(trace_digest.span_completion_tokens(s) for s in spans),
        sum(trace_digest.span_cache_read_tokens(s) for s in spans),
    )


def _unique_name(directory: Path, stem: str, suffix: str) -> Path:
    name = directory / f"{stem}{suffix}"
    counter = 2
    while name.exists():
        name = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return name


def export_batch(client, settings, batch_id: str, out_dir, experiment=None) -> dict:
    """Fetch the traces of one batch and write the export layout.

    Writes ``manifest.jsonl`` (one line per task), ``traces/<task>.json``
    (full trace_to_dict dump), ``digests/<task>.md`` and ``summary.md``.
    Raises :class:`TraceBatchNotFound` when the batch has no traces.
    Returns a small summary dict (batch_id, traces, tasks, tokens).
    """
    out_dir = Path(out_dir)
    traces = find_batch_traces(client, settings, batch_id, experiment=experiment)
    if not traces:
        experiment_label = (
            experiment
            or "family experiments discovered from MLflow runs (plus legacy fallback)"
        )
        raise TraceBatchNotFound(batch_id, experiment_label)

    traces_dir = out_dir / "traces"
    digests_dir = out_dir / "digests"
    traces_dir.mkdir(parents=True, exist_ok=True)
    digests_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines: list[dict] = []
    total_in = total_out = 0
    for trace in traces:
        data = trace_to_dict(trace)
        task = str(data.get("task") or "unknown")
        prompt_tokens, completion_tokens, cache_read = _trace_tokens(data)
        total_in += prompt_tokens
        total_out += completion_tokens
        (traces_dir / f"{task}.json").write_text(
            json.dumps(data, indent=2, default=str)
        )
        (digests_dir / f"{task}.md").write_text(
            trace_digest.build_digest(data)
        )
        phase_tokens = trace_digest.trace_phase_tokens(data)
        line = {
            "task": task,
            "trace_id": data.get("trace_id"),
            "state": data.get("state"),
            "tokens_in": prompt_tokens,
            "tokens_out": completion_tokens,
            "signals": trace_digest.trace_signals(data),
        }
        # Only when the endpoint reports cache reads; legacy traces keep
        # the exact previous manifest shape.
        if cache_read:
            line["tokens_cache_read"] = cache_read
        # Per-phase token totals (absent for legacy traces without
        # phase-named agent spans). Issue #73.
        if phase_tokens:
            line["phase_tokens"] = phase_tokens
        manifest_lines.append(line)
    (out_dir / "manifest.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in manifest_lines)
    )
    (out_dir / "summary.md").write_text(
        _summary_md(batch_id, manifest_lines, total_in, total_out)
    )
    return {
        "batch_id": batch_id,
        "traces": len(manifest_lines),
        "tasks": [line["task"] for line in manifest_lines],
        "tokens_in": total_in,
        "tokens_out": total_out,
        "out_dir": str(out_dir),
    }


def _summary_md(
    batch_id: str,
    manifest_lines: list[dict],
    total_in: int,
    total_out: int,
) -> str:
    states: dict[str, int] = {}
    signal_counts: dict[str, int] = {}
    for line in manifest_lines:
        state = str(line.get("state") or "?")
        states[state] = states.get(state, 0) + 1
        for signal in line.get("signals") or []:
            signal_counts[signal] = signal_counts.get(signal, 0) + 1
    lines = [
        f"# Batch trace export: {batch_id}",
        "",
        f"- traces: {len(manifest_lines)}",
        f"- tasks: {', '.join(line['task'] for line in manifest_lines)}",
        f"- states: {', '.join(f'{k} x{v}' for k, v in sorted(states.items()))}",
        f"- tokens: {total_in} in / {total_out} out "
        f"(total {total_in + total_out})",
        f"- generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Signals",
        "",
    ]
    if signal_counts:
        for signal, count in sorted(signal_counts.items()):
            lines.append(f"- {signal} ({count} trace(s))")
    else:
        lines.append("No failure signals.")
    lines += [
        "",
        "## Tasks",
        "",
        "| task | trace_id | state | tokens in/out | signals |",
        "|---|---|---|---|---|",
    ]
    for line in manifest_lines:
        signals = ", ".join(line.get("signals") or []) or "-"
        lines.append(
            f"| {line['task']} | {line.get('trace_id')} "
            f"| {line.get('state')} | {line['tokens_in']}/{line['tokens_out']} "
            f"| {signals} |"
        )
    lines.append("")
    return "\n".join(lines)


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
