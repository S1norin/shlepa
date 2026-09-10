"""Opt-in OpenTelemetry tracing for the shlepa agent.

Enable with SLEPA_OTEL_ENABLED=1 and the `telemetry` extra
(``uv run --project agent --extra telemetry``). Spans are exported
via OTLP/HTTP to OTEL_EXPORTER_OTLP_ENDPOINT (default
http://localhost:4318, i.e. the local otel/ collector).

Span attribute values are truncated at a byte cap (default 8 KB,
``SLEPA_OTEL_ATTR_LIMIT`` / ``OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT``):
the OpenInference instrumentation embeds full tool stdout and whole
conversation message arrays in span attributes, and at the OTel spec
default (128 KB per value) dev runs export gigabytes of spans a day.

Nothing in this module is imported unless tracing is explicitly
requested, so the baseline stays clean of the otel SDK.
"""

from __future__ import annotations

import json
import os
import weakref
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from shlepa_agent import __version__

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

try:
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
except ImportError:  # baseline has no otel SDK; configure() is the only path
    ReadableSpan = None  # type: ignore[assignment, misc]
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
    ("SLEPA_EXECUTION_ID", "shlepa.execution_id"),
    ("SLEPA_PRESET", "shlepa.preset"),
    ("SLEPA_GIT_SHA", "git.commit"),
    ("SLEPA_AGENT_VERSION", "shlepa.agent_version"),
)

#: Default cap (bytes) for one span attribute value. The OpenInference
#: instrumentation embeds full tool stdout and whole conversation message
#: arrays into span attributes; at the OTel spec default (128 KB per value)
#: a dev run exports gigabytes of span traffic per day. Raise or lower it
#: with SLEPA_OTEL_ATTR_LIMIT, or override with the standard
#: OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT.
_DEFAULT_ATTR_LIMIT = 8192


def _span_attr_limit() -> int:
    """Byte cap for span attribute values.

    Precedence: OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT (standard OpenTelemetry
    variable) > SLEPA_OTEL_ATTR_LIMIT (shlepa dev knob) > 8192. Non-integer
    values fall back to the default.
    """
    raw = (
        os.environ.get("OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT")
        or os.environ.get("SLEPA_OTEL_ATTR_LIMIT")
        or str(_DEFAULT_ATTR_LIMIT)
    )
    try:
        return int(raw)
    except ValueError:  # pragma: no cover - defensive
        return _DEFAULT_ATTR_LIMIT


# Weakref to the currently open agent.run root span, so
# _ShlepaSpanProcessor can stamp late attributes (cumulative tokens) on it
# while it is still recording. Runs are sequential per process, one ref is
# enough. None when no root span is open.
_ROOT_SPAN_REF: "weakref.ref[Any] | None" = None

# The configured TracerProvider (set by :func:`configure`), so exit paths
# and the span processor can force_flush without the caller threading the
# provider through. None in the baseline (no otel SDK) and in tests that
# build their own provider without calling configure().
_PROVIDER: TracerProvider | None = None

#: Flush window (ms) after each finished LLM span: long enough for the
#: local collector to receive it, short enough not to stall the run.
_LLM_FLUSH_MILLIS = 1500

#: Flush window (ms) on run exit paths: termination is the last fact
#: about the run, give the flush the full default 5 s.
_EXIT_FLUSH_MILLIS = 5000


def flush_spans(timeout_millis: int = _EXIT_FLUSH_MILLIS) -> None:
    """Best-effort ``force_flush`` of the configured provider.

    Called after every finished LLM span (short window) and on every run
    exit path (long window), so a hard docker exec timeout right after
    the last LLM call — or a SIGTERM — loses at most one in-flight batch
    (#126). No-op when no provider is configured. Never raises.
    """
    try:
        provider = _PROVIDER
        if provider is not None:
            provider.force_flush(timeout_millis)
    except Exception:  # pragma: no cover - defensive, must never raise
        pass


def _install_exit_flush_hooks() -> None:
    """SIGTERM + atexit backstop for the span flush.

    docker exec's hard timeout kills with SIGKILL (nothing is flushable
    after that); SIGTERM and clean interpreter exit are flushable, so
    cover them once per process instead of in every entrypoint. The
    handler restores the default SIGTERM disposition and re-raises, so
    death semantics stay unchanged. Never raises.
    """
    try:
        import atexit

        atexit.register(lambda: flush_spans(_EXIT_FLUSH_MILLIS))
    except Exception:  # pragma: no cover - defensive
        pass
    try:
        import signal

        def _on_sigterm(signum: int, frame: Any) -> None:
            flush_spans(_EXIT_FLUSH_MILLIS)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        signal.signal(signal.SIGTERM, _on_sigterm)
    except Exception:  # pragma: no cover - non-main thread / odd envs
        pass


# The pipeline phase currently being executed (F4: per-span phase labels).
# Set by the runner around each phase execution (and its final_ask); the
# span processor copies it onto every span started inside the phase so
# traces can be read as PLAN -> WORK -> REVIEW. None outside a phase.
_PHASE_ID: ContextVar[str | None] = ContextVar("shlepa_phase_id", default=None)


@contextmanager
def phase_context(phase_id: str):
    """Mark the current execution as ``phase_id`` for the duration.

    Spans started inside the block (tool calls, LLM requests, final_ask)
    are stamped with ``shlepa.phase_id`` by :class:`_ShlepaSpanProcessor`.
    Restores the previous phase on exit.
    """
    token = _PHASE_ID.set(phase_id)
    try:
        yield
    finally:
        _PHASE_ID.reset(token)


def current_phase_id() -> str | None:
    """The phase id of the current execution context, if any."""
    return _PHASE_ID.get()


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
# Prompt-cache token keys (0/absent when the endpoint does not report
# caching). Instrumentation versions emit different key families (the
# gen_ai.usage.* first-class attributes and the gen_ai.usage.details.*
# legacy family carry the same counts on current traces; OpenAI-flavoured
# builds name the write axis cache_creation). First present key wins.
_CACHE_READ_KEYS = (
    "gen_ai.usage.cache_read.input_tokens",
    "gen_ai.usage.details.cache_read_tokens",
)
_CACHE_WRITE_KEYS = (
    "gen_ai.usage.cache_write.input_tokens",
    "gen_ai.usage.cache_creation.input_tokens",
    "gen_ai.usage.details.cache_write_tokens",
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
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        try:
            batch_id = os.environ.get("SLEPA_BATCH_ID")
            if batch_id and "shlepa.batch_id" not in span.attributes:
                span.set_attribute("shlepa.batch_id", batch_id)
            task_slug = os.environ.get("SLEPA_TASK_SLUG")
            if task_slug and "task" not in span.attributes:
                span.set_attribute("task", task_slug)
            phase_id = current_phase_id()
            if phase_id and "shlepa.phase_id" not in span.attributes:
                span.set_attribute("shlepa.phase_id", phase_id)
        except Exception:  # pragma: no cover - defensive, must never raise
            pass

    def on_end(self, span: Any) -> None:
        try:
            if self._accumulate_tokens(span):
                # #126: push the finished LLM span to the collector while
                # the process is still alive; a kill right after the last
                # LLM call then loses almost nothing.
                flush_spans(_LLM_FLUSH_MILLIS)
        except Exception:  # pragma: no cover - defensive, must never raise
            pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _accumulate_tokens(self, span: Any) -> bool:
        """Accumulate LLM token usage and stamp the open root span.

        Returns True when the span carried LLM usage (so the caller can
        trigger a flush, #126).
        """
        attrs = span.attributes or {}
        prompt = self._first_present(attrs, _PROMPT_TOKEN_KEYS)
        completion = self._first_present(attrs, _COMPLETION_TOKEN_KEYS)
        if prompt is None and completion is None:
            return False  # not an LLM span: nothing to count
        cache_read = self._first_present(attrs, _CACHE_READ_KEYS)
        cache_write = self._first_present(attrs, _CACHE_WRITE_KEYS)
        if prompt is not None:
            self._prompt_tokens += int(prompt)
        if completion is not None:
            self._completion_tokens += int(completion)
        if cache_read is not None:
            self._cache_read_tokens += int(cache_read)
        if cache_write is not None:
            self._cache_write_tokens += int(cache_write)
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
            # Cache attrs only when non-zero: endpoints without cache
            # reporting keep the root span clean.
            if self._cache_read_tokens:
                root.set_attribute(
                    "shlepa.llm.cumulative_cache_read_tokens",
                    self._cache_read_tokens,
                )
            if self._cache_write_tokens:
                root.set_attribute(
                    "shlepa.llm.cumulative_cache_write_tokens",
                    self._cache_write_tokens,
                )
        return True

    @staticmethod
    def _first_present(attrs: Any, keys: tuple[str, ...]) -> int | None:
        for key in keys:
            value = attrs.get(key)
            if value is not None:
                return value
        return None


def _thinking_and_answer(messages: Any) -> tuple[list[str], str] | None:
    """Extract thinking parts (and text parts as a fallback answer) from a
    ``gen_ai.output.messages`` value.

    Returns ``(thinking_parts, text_answer)`` or ``None`` when there is no
    thinking (or the value is not a messages list).
    """
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except ValueError:
            return None
    if not isinstance(messages, (list, tuple)):
        return None
    thinking: list[str] = []
    texts: list[str] = []
    tool_calls: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            content = str(part.get("content") or "")
            if part_type == "thinking" and content:
                thinking.append(content)
            elif part_type == "text" and content:
                texts.append(content)
            elif part_type == "tool_call":
                name = str(part.get("name") or "tool")
                args = part.get("arguments")
                if args is None:
                    tool_calls.append(f"{name}()")
                elif isinstance(args, str):
                    tool_calls.append(f"{name}({args})")
                else:
                    try:
                        tool_calls.append(
                            f"{name}({json.dumps(args, default=str)})"
                        )
                    except ValueError:  # pragma: no cover - defensive
                        tool_calls.append(f"{name}()")
    if not thinking:
        return None
    if texts:
        return thinking, "\n".join(texts)
    if tool_calls:
        return thinking, "tool_calls: " + ", ".join(tool_calls)
    return thinking, ""


def _enrich_span_output(span: ReadableSpan) -> ReadableSpan:
    """Return a copy of an LLM span with its reasoning in the span output.

    The MLflow trace UI shows span output from ``output.value`` (the server
    copies it to ``mlflow.spanOutputs``). The pydantic-ai / OpenInference
    instrumentation puts reasoning into the ``type: "thinking"`` parts of
    ``gen_ai.output.messages`` while ``output.value`` carries only the final
    text, so reasoning looks absent. For spans that do carry thinking parts
    this returns a span copy with ``output.value`` / ``mlflow.spanOutputs``
    rewritten to ``<thinking>...</thinking>`` followed by the answer; every
    other span passes through unchanged.
    """
    try:
        attrs = dict(span.attributes or {})
        found = _thinking_and_answer(attrs.get("gen_ai.output.messages"))
        if found is None or ReadableSpan is None:
            return span
        thinking, text_answer = found
        answer = str(attrs.get("output.value") or "") or text_answer
        if not answer:
            answer = "(no final text)"
        enriched = (
            "<thinking>\n" + "\n".join(thinking) + "\n</thinking>\n\n" + answer
        )
        attrs["output.value"] = enriched
        attrs["mlflow.spanOutputs"] = enriched
        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=attrs,
            events=span.events,
            links=span.links,
            kind=span.kind,
            status=span.status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )
    except Exception:  # pragma: no cover - defensive, must never raise
        return span


class _ThinkingEnrichingExporter:
    """Span exporter wrapper that surfaces reasoning in span outputs.

    Runs right before the real exporter (see :func:`configure`), so the
    enrichment is invisible to span processors and to the agent itself.
    """

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def export(self, spans: Any) -> Any:
        return self._delegate.export(
            [_enrich_span_output(span) for span in spans]
        )

    def shutdown(self) -> None:
        shutdown = getattr(self._delegate, "shutdown", None)
        if shutdown is not None:
            shutdown()

    def force_flush(self, timeout_millis: int | None = None) -> bool:
        flush = getattr(self._delegate, "force_flush", None)
        if flush is None:
            return True
        return flush(timeout_millis)


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
            # ended (crash vs. handled timeout). Entrypoints that already
            # stamped a specific reason via mark_termination (e.g.
            # 'crash:<Exc>') keep it; this is only the generic fallback.
            already = "shlepa.termination_reason" in getattr(span, "attributes", {}) or {}
            if not already:
                span.set_attribute("shlepa.termination_reason", "crash")
            raise
        finally:
            # #126: flush on both exit paths. Entrypoints also flush via
            # provider.shutdown() afterwards; a double flush is harmless.
            flush_spans(_EXIT_FLUSH_MILLIS)


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
    # #126: the termination reason is the last fact about the run — make
    # sure it leaves the process.
    flush_spans(_EXIT_FLUSH_MILLIS)


#: Cap for free-text values stamped onto spans (F4): the trace UI and the
#: digest builder should stay readable; full transcripts live in the
#: per-task trace JSON anyway.
_TEXT_CAP = 16_000


def _capped(value: str, limit: int = _TEXT_CAP) -> str:
    value = str(value)
    return value if len(value) <= limit else value[:limit] + " [truncated]"


def _current_recording_span() -> Any | None:
    """The active recording span, or None (SDK absent / no span open)."""
    try:
        from opentelemetry import trace
    except ImportError:  # baseline without the otel extra
        return None
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return None
    return span


def mark_input(value: str) -> None:
    """Stamp ``input.value`` (the task instruction) on the current span.

    Called from the runner while the agent.run root span is open (F4): the
    trace then carries the instruction directly instead of hiding it inside
    the first LLM span. No-op when there is no active recording span or the
    SDK is not installed. Never raises.
    """
    try:
        span = _current_recording_span()
        if span is not None:
            span.set_attribute("input.value", _capped(value))
    except Exception:  # pragma: no cover - defensive, must never raise
        pass


def mark_outcome(status: str, output: str = "") -> None:
    """Stamp ``shlepa.status`` + ``output.value`` on the current span (F4).

    The final pipeline status (done/timeout/error) and, when present, the
    final output text. Complements shlepa.termination_reason, which only
    covers crash/timeout exits. No-op rules as in :func:`mark_input`.
    Never raises.
    """
    try:
        span = _current_recording_span()
        if span is not None:
            span.set_attribute("shlepa.status", status)
            if output:
                span.set_attribute("output.value", _capped(output))
    except Exception:  # pragma: no cover - defensive, must never raise
        pass


@contextmanager
def final_ask_span(phase_id: str, prompt: str, provider: Any | None = None):
    """Span for one toolless final_ask request (F4).

    Carries the triggering phase id (``shlepa.phase_id``) and the prompt on
    start; the caller stamps ``shlepa.ok`` / ``output.value`` before
    exiting. ``provider`` is optional (tests inject their TracerProvider);
    by default the globally configured one is used. Yields the span, or
    None when the otel SDK is unavailable (baseline path), so the caller
    guards attribute writes on a non-None span. A failure to open the span
    degrades to a None yield, never a raised error: telemetry must not
    break the run.
    """
    try:
        if provider is not None:
            tracer = provider.get_tracer("shlepa-agent")
        else:
            from opentelemetry import trace

            tracer = trace.get_tracer("shlepa-agent")
    except Exception:  # pragma: no cover - baseline without the otel extra
        yield None
        return
    with tracer.start_as_current_span("final_ask") as span:
        span.set_attribute("shlepa.phase_id", phase_id)
        span.set_attribute("input.value", _capped(prompt, 4000))
        yield span


def configure(exporter: Any | None = None) -> TracerProvider:
    """Set up the global tracer provider and return it.

    ``exporter`` is injectable for tests (e.g. InMemorySpanExporter);
    by default an OTLP/HTTP exporter pointed at
    OTEL_EXPORTER_OTLP_ENDPOINT is used. Also registers the exit flush
    hooks (SIGTERM + atexit, #126) and stores the provider for
    :func:`flush_spans`.
    """
    global _PROVIDER
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import SpanLimits, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        # No explicit endpoint: the exporter reads OTEL_EXPORTER_OTLP_ENDPOINT
        # (or OTEL_EXPORTER_OTLP_TRACES_ENDPOINT) itself and appends the
        # /v1/traces path; passing endpoint= would skip the path append.
        exporter = OTLPSpanExporter()

    # Rewrite LLM span outputs to include reasoning before export (dev-only;
    # the submission zip never ships this module).
    exporter = _ThinkingEnrichingExporter(exporter)

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "shlepa-agent",
                "service.version": __version__,
            }
        ),
        # Cap span attribute values (full tool stdout, conversation message
        # arrays) so exported traces stay small; see _span_attr_limit.
        span_limits=SpanLimits(max_span_attribute_length=_span_attr_limit()),
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

    _PROVIDER = provider
    _install_exit_flush_hooks()
    trace.set_tracer_provider(provider)
    return provider
