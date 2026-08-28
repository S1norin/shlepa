"""Opt-in OpenTelemetry tracing for the shlepa agent.

Enable with SLEPA_OTEL_ENABLED=1 and the `telemetry` extra
(``uv run --project agent --extra telemetry``). Spans are exported
via OTLP/HTTP to OTEL_EXPORTER_OTLP_ENDPOINT (default
http://localhost:4318, i.e. the local otel/ collector).

Nothing in this module is imported unless tracing is explicitly
requested, so the baseline stays clean of the otel SDK.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from shlepa_agent import __version__

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider


def is_enabled() -> bool:
    """True when SLEPA_OTEL_ENABLED is set to '1'."""
    return os.environ.get("SLEPA_OTEL_ENABLED") == "1"


# Root-span attributes stamped from environment, in (env var, attribute
# name) pairs. The dev run engine sets these so traces can be grouped per
# batch/preset and correlated with MLflow runs. Unset variables are simply
# omitted (no empty attributes).
_ENV_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("SLEPA_BATCH_ID", "shlepa.batch_id"),
    ("SLEPA_PRESET", "shlepa.preset"),
    ("SLEPA_GIT_SHA", "git.commit"),
    ("SLEPA_AGENT_VERSION", "shlepa.agent_version"),
)


@contextmanager
def root_span(provider: TracerProvider, task: str | None = None):
    """Context manager for the per-run 'agent.run' root span.

    Carries the task slug (``task`` argument or the SLEPA_TASK_SLUG
    environment variable, falling back to 'dev-run') so traces can be
    grouped per task, plus shlepa.* identity attributes from the
    environment (see _ENV_ATTRIBUTES). Used by both agent entrypoints
    (the submission ``__main__`` and the in-container dev entrypoint).
    """
    task_name = task or os.environ.get("SLEPA_TASK_SLUG") or "dev-run"
    tracer = provider.get_tracer("shlepa-agent")
    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("task", task_name)
        for env_var, attr in _ENV_ATTRIBUTES:
            value = os.environ.get(env_var)
            if value:
                span.set_attribute(attr, value)
        try:
            yield span
        except Exception:
            # start_as_current_span records the ERROR status automatically;
            # the reason attribute tells the digest builder WHY the run
            # ended (crash vs. handled timeout).
            span.set_attribute("shlepa.termination_reason", "crash")
            raise


def mark_termination(reason: str) -> None:
    """Stamp the active span with ``shlepa.termination_reason`` + ERROR status.

    Used by entrypoints that handle a termination themselves (e.g. the
    in-container dev entrypoint catches asyncio.TimeoutError and exits
    without raising), so the trace still reflects how the run ended.
    No-op when there is no active recording span.
    """
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode

    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    span.set_attribute("shlepa.termination_reason", reason)
    span.set_status(Status(StatusCode.ERROR, reason))


def configure(exporter: Any | None = None) -> TracerProvider:
    """Set up the global tracer provider and return it.

    ``exporter`` is injectable for tests (e.g. InMemorySpanExporter);
    by default an OTLP/HTTP exporter pointed at
    OTEL_EXPORTER_OTLP_ENDPOINT is used.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        # No explicit endpoint: the exporter reads OTEL_EXPORTER_OTLP_ENDPOINT
        # (or OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) itself and appends the
        # /v1/traces path; passing endpoint= would skip the path append.
        exporter = OTLPSpanExporter()

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "shlepa-agent",
                "service.version": __version__,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))

    try:
        from openinference.instrumentation.pydantic_ai import (
            OpenInferenceSpanProcessor,
        )

        provider.add_span_processor(OpenInferenceSpanProcessor())
    except ImportError:  # pragma: no cover - extra is incomplete
        pass

    trace.set_tracer_provider(provider)
    return provider
