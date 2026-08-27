# otel/ — local telemetry stack (collector + Jaeger + MLflow)

Local OpenTelemetry pipeline for `shlepa-agent` traces. The collector
**dual-exports** every trace:

```
agent (OTLP) --> otelcol (localhost:4318 http / 4317 grpc)
                   |---> Jaeger (UI :16686, local debugging, volume-backed)
                   +----> remote MLflow server (durable backend, OTLP/HTTP)
```

The MLflow exporter is stateless transport only — credentials and the
destination experiment live in `otel/.env` (gitignored; see
`otel/.env.example`), never in the agent.

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

## MLflow export configuration (`otel/.env`)

```bash
cp otel/.env.example otel/.env   # then fill in real values
```

- `MLFLOW_BASIC_B64` — base64 of `<user>:<password>`
  (`printf '%s:%s' "$USER" "$PASS" | base64 -w0`); sent as
  `Authorization: Basic ...` on every export.
- `MLFLOW_TELEMETRY_EXPERIMENT_ID` — numeric id of the trace experiment
  (the collector can only reference it by id; the agent's traces land in
  the `shlepa-traces` experiment on the remote server).

The exporter targets `https://mlflow.sinorin.ru` and appends the OTLP
signal path `/v1/traces` itself (MLflow 3.6+ OTLP ingestion; the server
runs 3.15.x). Compression: gzip. After changing `otel/.env`, restart the
collector (`docker compose -f otel/docker-compose.yml restart otelcol`).

## Send a test span

One-liner from the repo root (uses the agent's own telemetry module, so it
exercises the exact same exporter path as a real run):

```bash
SLEPA_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  uv run --project agent --extra telemetry python -c 'import os; from shlepa_agent.telemetry import configure; from opentelemetry import trace; configure(); tp = trace.get_tracer_provider(); span = tp.get_tracer("shlepa-smoke").start_span("shlepa.smoke.test"); span.set_attribute("smoke", "1"); span.end(); from opentelemetry.sdk.trace import TracerProvider; tp.shutdown()'
```

Then open <http://localhost:16686> → select service `shlepa-agent`, span
`shlepa.smoke.test`; or query the API (Jaeger 2.x needs a time window —
a bare query may return an empty result for fresh traces):

```bash
curl -s 'http://localhost:16686/api/traces?service=shlepa-agent&limit=1&lookback=24h' | head -c 400
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

Exit code 0 = a valid trace is present, 1 = the backend is unreachable, no
traces, or the trace lacks the expected spans/attributes. Options:
`--backend jaeger|mlflow` (default `jaeger`), `--jaeger`, `--service`
(default `shlepa-agent`), `--timeout`. The script picks the most recent trace
of the service, so a fresh run is checked, not an older one.

MLflow backend (durable export via the collector):

```bash
source .env  # MLFLOW_TRACKING_URI / USERNAME / PASSWORD
uv run --project cli --no-sync python otel/check_trace.py --backend mlflow
# OK: trace tr-... (N spans, LLM span with token usage, task attribute present)
```

Reads the experiment from `SLEPA_TRACE_EXPERIMENT` (default `shlepa-traces`) —
only traces tagged `service.name=shlepa-agent` are considered. Note: the
collector exports to the remote server asynchronously, so give it a few
seconds after the run finishes.

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

## Remote MLflow backend (live)

The remote MLflow server (3.15.x) accepts OTLP/HTTP ingestion at
`POST /v1/traces` (basic auth + `x-mlflow-experiment-id` header). The local
collector forwards every trace there, so the remote server is the durable
backend: MLflow runs (from `shlepa run`) live next to the agent traces in
the same server, correlated by the `batch_id` run tag and the
`shlepa.batch_id` trace tag (see the run engine).

Verified facts (2026-08):
- `GET https://mlflow.sinorin.ru/version` → 3.15.1
- `POST /v1/traces` without auth → 401; with basic auth +
  `x-mlflow-experiment-id` → 200, trace visible via `mlflow.search_traces`
- the OTLP/gRPC path is **not** served (404); use OTLP/HTTP

Retention: no archival policy is configured; archived span payloads keep
tag filtering but lose full-text search.
