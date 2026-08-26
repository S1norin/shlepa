# otel/ — local telemetry stack (collector + Jaeger)

Local OpenTelemetry pipeline for `shlepa-agent` traces:

```
agent (OTLP) --> otelcol (localhost:4318 http / 4317 grpc) --> Jaeger (UI :16686)
```

## Usage

```bash
docker compose -f otel/docker-compose.yml up -d      # start (pulls images first time)
docker compose -f otel/docker-compose.yml down       # stop (volume keeps traces)
docker compose -f otel/docker-compose.yml down -v    # stop + delete stored traces
docker logs -f otelcol                               # watch received spans
```

| Port | Service |
|------|---------|
| 127.0.0.1:4318 | OTLP/HTTP receiver (collector) |
| 127.0.0.1:4317 | OTLP/gRPC receiver (collector) |
| 127.0.0.1:16686 | Jaeger UI |

All ports are bound to localhost only. Jaeger stores traces in the
`jaeger-traces` Docker volume, so they survive restarts.

## Send a test span

One-liner from the repo root (uses the agent's own telemetry module, so it
exercises the exact same exporter path as a real run):

```bash
SLEPA_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run --project agent --extra telemetry python -c 'import os; from shlepa_agent.telemetry import configure; from opentelemetry import trace; configure(); tp = trace.get_tracer_provider(); span = tp.get_tracer("shlepa-smoke").start_span("shlepa.smoke.test"); span.set_attribute("smoke", "1"); span.end(); from opentelemetry.sdk.trace import TracerProvider; tp.shutdown()'
```

Then open <http://localhost:16686> → select service `shlepa-agent`, span
`shlepa.smoke.test`; or query the API:

```bash
curl -s 'http://localhost:16686/api/traces?service=shlepa-agent&limit=1' | head -c 400
```

A real agent run produces the same flow automatically: with
`SLEPA_OTEL_ENABLED=1` the dev CLI's `run`/`smoke` commands emit pydantic-ai
spans (see the agent telemetry module) to the same endpoint.

## What spans carry

pydantic-ai instrumentation emits spans with OpenAI Inference (`gen_ai.*`)
attributes: model name, token usage, prompt/completion content, tool calls
(bash/read_file/apply_diff/append_file) and their results. Service resource:
`service.name=shlepa-agent`, `service.version=<agent version>`. MLflow runs
created by `shlepa run` get a `trace_ref` tag pointing at this Jaeger when
`SLEPA_OTEL_ENABLED=1`.

## Remote MLflow cutover (future)

The remote MLflow server (3.15.1) currently has **no OTLP endpoint**
(verified). When/where it gains one, the cutover is a single `.env` line:

```
OTEL_EXPORTER_OTLP_ENDPOINT=https://mlflow.sinorin.ru/<otlp-path>
```

No code changes: the agent telemetry module already reads
`OTEL_EXPORTER_OTLP_ENDPOINT`. The mapping of OTel spans onto MLflow trace
entities (MLflow 3 "GenAI tracing" model) is to be designed at cutover time.
