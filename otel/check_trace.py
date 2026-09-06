"""Verify the dev telemetry path end-to-end (Jaeger or MLflow backend).

Queries the chosen backend for the most recent trace of the agent
service and asserts it contains what the data model promises:

- at least one LLM span (openinference.span.kind == "LLM")
- token-usage attributes (gen_ai.usage.input_tokens / output_tokens)
  on an LLM span
- a "task" attribute on some span (set by the agent root span)

Backends:
    jaeger   - Jaeger HTTP API (default), no dependencies
    mlflow   - remote MLflow server via the mlflow client; run under the
               CLI venv:  uv run --project cli --no-sync python otel/check_trace.py
                          --backend mlflow
               Reads MLFLOW_TRACKING_URI / MLFLOW_TRACKING_USERNAME /
               MLFLOW_TRACKING_PASSWORD from the environment.

Usage:
    python otel/check_trace.py [--backend jaeger|mlflow]
                               [--jaeger http://localhost:16686]
                               [--experiment <family-name-or-id>]
                               [--service shlepa-agent] [--timeout 10]

Exit codes: 0 when a valid trace is found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass

DEFAULT_JAEGER = "http://localhost:16686"
DEFAULT_SERVICE = "shlepa-agent"
# Wide window: the MLflow search is unordered, so a small limit can
# exclude the just-finished trace from the candidate set entirely.
TRACE_LIMIT = 500

LLM_KIND_KEY = "openinference.span.kind"
LLM_KIND = "LLM"
TOKEN_USAGE_KEYS = ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens")
TASK_KEY = "task"


@dataclass
class TraceCheck:
    """Outcome of validating one trace."""

    ok: bool
    detail: str
    trace_id: str | None = None


def _span_end(span: dict) -> int:
    return int(span.get("startTime", 0)) + int(span.get("duration", 0))


def latest_trace(payload: dict) -> dict | None:
    """Return the most recently finished trace from a Jaeger API payload.

    The Jaeger query API returns traces in arbitrary order; "most recent"
    means the largest span end time (startTime + duration) in the trace.
    """
    traces = payload.get("data") or []
    if not traces:
        return None
    return max(traces, key=lambda t: max((_span_end(s) for s in t.get("spans", [])), default=0))


def _span_tags(span: dict) -> dict:
    return {t.get("key"): t.get("value") for t in span.get("tags", []) if t.get("key")}


def _validate_spans(trace_id: str | None, spans: list[dict]) -> TraceCheck:
    """Validate normalized span attribute maps against the agent data model.

    ``spans`` is a list of attribute dicts (one per span); span names are
    irrelevant for the checks. Shared by both backends.
    """
    llm_tags = [attrs for attrs in spans if attrs.get(LLM_KIND_KEY) == LLM_KIND]
    if not llm_tags:
        return TraceCheck(False, "no LLM span (openinference.span.kind=LLM) found", trace_id)

    if not any(k in attrs for attrs in llm_tags for k in TOKEN_USAGE_KEYS):
        return TraceCheck(False, "no token-usage attributes on LLM span", trace_id)

    if not any(TASK_KEY in attrs for attrs in spans):
        return TraceCheck(False, "no 'task' attribute on any span", trace_id)

    detail = f"{len(spans)} spans, LLM span with token usage, task attribute present"
    return TraceCheck(True, detail, trace_id)


def check_trace(trace: dict) -> TraceCheck:
    """Validate one Jaeger trace dict against the agent data model."""
    trace_id = trace.get("traceID")
    tag_maps = [_span_tags(s) for s in trace.get("spans", [])]
    return _validate_spans(trace_id, tag_maps)


def check_mlflow_trace(trace) -> TraceCheck:
    """Validate one MLflow Trace object (info.trace_id, data.spans).

    Spans are read via their public ``name``/``attributes`` surface, so the
    function works with the real mlflow client objects and with plain
    stand-ins in tests.
    """
    trace_id = getattr(trace.info, "trace_id", None)
    spans = [dict(s.attributes or {}) for s in trace.data.spans]
    return _validate_spans(trace_id, spans)


def fetch_latest_trace(
    base_url: str, service: str = DEFAULT_SERVICE, timeout: float = 10.0
) -> dict | None:
    """Query the Jaeger API and return the most recent trace or None."""
    url = f"{base_url}/api/traces?service={service}&limit={TRACE_LIMIT}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
    return latest_trace(payload)


def fetch_latest_mlflow_trace(
    tracking_uri: str,
    username: str | None,
    password: str | None,
    experiment: str,
    service: str = DEFAULT_SERVICE,
    timeout: float = 30.0,
):
    """Query the MLflow server and return the newest matching trace.

    Runs under the CLI venv (which has the mlflow client). The tracking
    URI is passed with embedded basic-auth credentials, as the MLflow 3.x
    client no longer accepts username/password kwargs. ``experiment`` is a
    name; only traces tagged with service.name == ``service`` are
    considered (newest by request_time).
    """
    import warnings
    from urllib.parse import quote, urlsplit, urlunsplit

    import mlflow

    parts = urlsplit(tracking_uri)
    port = f":{parts.port}" if parts.port else ""
    host_port = f"{parts.hostname}{port}"
    if username:
        netloc = (
            f"{quote(username, safe='')}"
            f":{quote(password or '', safe='')}@{host_port}"
        )
    else:
        netloc = host_port
    mlflow.set_tracking_uri(
        urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    )

    exp = mlflow.get_experiment_by_name(experiment)
    if exp is None:
        return None

    with warnings.catch_warnings():
        # experiment_ids is deprecated in favour of locations, but the
        # locations query path hangs on the current server; revisit later.
        warnings.simplefilter("ignore", FutureWarning)
        df = mlflow.search_traces(
            experiment_ids=[exp.experiment_id], max_results=TRACE_LIMIT
        )
    if df is None or len(df) == 0:
        return None

    tags = df["tags"].apply(lambda t: (t or {}))
    rows = df[tags.apply(lambda t: t.get("service.name") == service)]
    if len(rows) == 0:
        return None
    newest = rows.sort_values("request_time", ascending=False, na_position="last").iloc[0]
    return mlflow.get_trace(newest["trace_id"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend", choices=("jaeger", "mlflow"), default="jaeger",
        help="trace backend to verify (default: jaeger)",
    )
    parser.add_argument("--jaeger", default=DEFAULT_JAEGER, help="Jaeger base URL")
    parser.add_argument(
        "--experiment",
        default=os.environ.get("SLEPA_TRACE_EXPERIMENT"),
        help=(
            "MLflow family experiment name for --backend mlflow "
            "(or set SLEPA_TRACE_EXPERIMENT)"
        ),
    )
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="service name")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout (s)")
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help=(
            "if the check fails, retry for up to N seconds (MLflow "
            "ingestion is async; 0 = no retry, default)"
        ),
    )
    args = parser.parse_args(argv)

    if args.backend == "mlflow":
        tracking_uri = os.environ.get("MLFLOW_TRACKING_URI")
        if not tracking_uri:
            print("FAIL: MLFLOW_TRACKING_URI is not set (see .env.example)")
            return 1
        if not args.experiment:
            print(
                "FAIL: --experiment is required for the MLflow backend "
                "(traces live in their run's family experiment)"
            )
            return 1
        # MLflow ingestion is async: right after a batch the newest trace
        # may not be searchable yet, so the check can validate a stale one
        # and false-FAIL. --wait retries until the deadline.
        deadline = time.monotonic() + args.wait
        while True:
            try:
                trace = fetch_latest_mlflow_trace(
                    tracking_uri,
                    os.environ.get("MLFLOW_TRACKING_USERNAME"),
                    os.environ.get("MLFLOW_TRACKING_PASSWORD"),
                    args.experiment,
                    service=args.service,
                )
            except Exception as exc:  # noqa: BLE001 - report any fetch failure
                print(f"FAIL: cannot query MLflow at {tracking_uri}: {type(exc).__name__}: {exc}")
                return 1
            if trace is None:
                message = (
                    f"FAIL: no traces found for service '{args.service}' "
                    f"in experiment '{args.experiment}'"
                )
                if time.monotonic() < deadline:
                    print(message + " (waiting for ingestion…)", file=sys.stderr)
                    time.sleep(5)
                    continue
                print(message)
                return 1
            result = check_mlflow_trace(trace)
            if result.ok:
                print(f"OK: trace {result.trace_id} ({result.detail})")
                return 0
            if time.monotonic() < deadline:
                print(
                    f"retry: trace {result.trace_id} not ready "
                    f"({result.detail}); waiting for a newer trace…",
                    file=sys.stderr,
                )
                time.sleep(5)
                continue
            print(f"FAIL: trace {result.trace_id}: {result.detail}")
            return 1

    try:
        trace = fetch_latest_trace(args.jaeger, args.service, args.timeout)
    except Exception as exc:  # noqa: BLE001 - report any fetch failure
        print(f"FAIL: cannot query Jaeger at {args.jaeger}: {type(exc).__name__}: {exc}")
        return 1

    if trace is None:
        print(f"FAIL: no traces found for service '{args.service}'")
        return 1

    result = check_trace(trace)
    if not result.ok:
        print(f"FAIL: trace {result.trace_id}: {result.detail}")
        return 1

    print(f"OK: trace {result.trace_id} ({result.detail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
