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
import weakref
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from shlepa_agent import __version__

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

try:
    from opentelemetry.sdk.trace import SpanProcessor
except ImportError:  # baseline has no otel SDK; configure() is the only path
    SpanProcessor = object  # type: ignore[assignment, misc]


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

# Weakref to the currently open agent.run root span, so
# _ShlepaSpanProcessor can stamp late attributes (cumulative tokens) on it
# while it is still recording. Runs are sequential per process, one ref is
# enough. None when no root span is open.
_ROOT_SPAN_REF: "weakref.ref[Any] | None" = None


def _set_root_ref(span: Any) -> None:
    """Register the open agent.run root span for late attribute stamping."""
    global _ROOT_SPAN_REF
    _ROOT_SPAN_REF = weakref.ref(span)


# LLM usage attribute keys, prompt/completion axes. First present key per
# axis wins; a span reporting both conventions is counted once.
_PROMPT_TOKEN_KEYS = ("llm.token_count.prompt", "gen_ai.usage.input_tokens")
_COMPLETION_TOKEN_KEYS = (
    "llm.token_count.completion",
    "gen_ai.usage.output_tokens",
)


class _ShlepaSpanProcessor(SpanProcessor):
    """Correlation + token accounting for shlepa traces.

    - on_start: copies SLEPA_BATCH_ID / SLEPA_TASK_SLUG onto every span as
      shlepa.batch_id / task, so a trace whose agent.run root span never
      flushes (docker kill on a hard exec timeout) still correlates by batch.
    - on_end: accumulates prompt/completion tokens from finished LLM spans
      and stamps the still-open agent.run root span with cumulative values,
      so timed-out runs report tokens for completed turns instead of 0.

    Never raises: telemetry must not break agent runs.
    """

    def __init__(self) -> None:
        self._prompt_tokens = 0
        self._completion_tokens = 0

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            batch_id = os.environ.get("SLEPA_BATCH_ID")
            if batch_id and "shlepa.batch_id" not in span.attributes:
                span.set_attribute("shlepa.batch_id", batch_id)
            task_slug = os.environ.get("SLEPA_TASK_SLUG")
            if task_slug and "task" not in span.attributes:
                span.set_attribute("task", task_slug)
        except Exception:  # pragma: no cover - defensive, must never raise
            pass

    def on_end(self, span: Any) -> None:
        try:
            self._accumulate_tokens(span)
        except Exception:  # pragma: no cover - defensive, must never raise
            pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _accumulate_tokens(self, span: Any) -> None:
        attrs = span.attributes or {}
        prompt = self._first_present(attrs, _PROMPT_TOKEN_KEYS)
        completion = self._first_present(attrs, _COMPLETION_TOKEN_KEYS)
        if prompt is None and completion is None:
            return  # not an LLM span: nothing to count
        if prompt is not None:
            self._prompt_tokens += int(prompt)
        if completion is not None:
            self._completion_tokens += int(completion)
        root_ref = _ROOT_SPAN_REF
        root = root_ref() if root_ref is not None else None
        if root is not None and root.is_recording():
            # The root span ends last, so it is still open when children
            # finish; stamping here is visible in its exported copy.
            root.set_attribute(
                "shlepa.llm.cumulative_prompt_tokens", self._prompt_tokens
            )
            root.set_attribute(
                "shlepa.llm.cumulative_completion_tokens",
                self._completion_tokens,
            )

    @staticmethod
    def _first_present(attrs: Any, keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = attrs.get(key)
            if value is not None:
                return value
        return None


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
        _set_root_ref(span)
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

    provider.add_span_processor(_ShlepaSpanProcessor())

    trace.set_tracer_provider(provider)
    return provider
