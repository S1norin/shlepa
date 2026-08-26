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
from typing import TYPE_CHECKING, Any

from shlepa_agent import __version__

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider


def is_enabled() -> bool:
    """True when SLEPA_OTEL_ENABLED is set to '1'."""
    return os.environ.get("SLEPA_OTEL_ENABLED") == "1"


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
