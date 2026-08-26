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

## Verify a trace (check_trace.py)

After a dev run with telemetry, verify the pipeline end-to-end (Jaeger
reachable, LLM span with token usage, task attribute present):

```bash
SLEPA_OTEL_ENABLED=1 uv run --project cli --no-sync shlepa run contest-hello-file
uv run --project cli --no-sync python otel/check_trace.py
# OK: trace <trace-id> (2 spans, LLM span with token usage, task attribute present)
```

Exit code 0 = a valid trace is present, 1 = Jaeger unreachable, no traces,
or the trace lacks the expected spans/attributes. Options: `--jaeger`,
`--service` (default `shlepa-agent`), `--timeout`. The script picks the most
recently finished trace of the service, so a fresh run is checked, not an
older one.

The `task` attribute comes from the agent's `agent.run` root span, which
reads `SLEPA_TASK_SLUG` (set by the dev run engine); ad-hoc runs without a
task slug get `task=dev-run`.

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
