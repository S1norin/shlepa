"""Verify the dev telemetry path end-to-end against Jaeger.

Queries the Jaeger HTTP API for the most recent trace of the agent
service and asserts it contains what the data model promises:

- at least one LLM span (openinference.span.kind == "LLM")
- token-usage attributes (gen_ai.usage.input_tokens / output_tokens)
  on an LLM span
- a "task" attribute on some span (set by the agent root span)

Usage:
    python otel/check_trace.py [--jaeger http://localhost:16686]
                               [--service shlepa-agent] [--timeout 10]

Exit codes: 0 when a valid trace is found, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass

DEFAULT_JAEGER = "http://localhost:16686"
DEFAULT_SERVICE = "shlepa-agent"
TRACE_LIMIT = 20

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


def check_trace(trace: dict) -> TraceCheck:
    """Validate one Jaeger trace dict against the agent data model."""
    trace_id = trace.get("traceID")
    spans = trace.get("spans", [])
    tag_maps = [_span_tags(s) for s in spans]

    llm_tags = [tags for tags in tag_maps if tags.get(LLM_KIND_KEY) == LLM_KIND]
    if not llm_tags:
        return TraceCheck(False, "no LLM span (openinference.span.kind=LLM) found", trace_id)

    if not any(k in tags for tags in llm_tags for k in TOKEN_USAGE_KEYS):
        return TraceCheck(False, "no token-usage attributes on LLM span", trace_id)

    if not any(TASK_KEY in tags for tags in tag_maps):
        return TraceCheck(False, "no 'task' attribute on any span", trace_id)

    detail = f"{len(spans)} spans, LLM span with token usage, task attribute present"
    return TraceCheck(True, detail, trace_id)


def fetch_latest_trace(
    base_url: str, service: str = DEFAULT_SERVICE, timeout: float = 10.0
) -> dict | None:
    """Query the Jaeger API and return the most recent trace or None."""
    url = f"{base_url}/api/traces?service={service}&limit={TRACE_LIMIT}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        payload = json.load(response)
    return latest_trace(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jaeger", default=DEFAULT_JAEGER, help="Jaeger base URL")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help="service name")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout (s)")
    args = parser.parse_args(argv)

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
