# otel/ — local telemetry stack (collector + Jaeger + MLflow)

Local OpenTelemetry pipeline for `shlepa-agent` traces. The collector
**dual-exports** every trace:

```
agent (OTLP) --> otelcol (localhost:4318 http / 4317 grpc)
                   |---> Jaeger (UI :16686, local debugging, in-memory <= 100k traces)
                   +----> remote MLflow server (durable backend, OTLP/HTTP)
```

The MLflow exporter is stateless transport only — credentials and the
destination experiment live in `otel/.env` (gitignored; see
`otel/.env.example`), never in the agent.

## Usage

```bash
docker compose -f otel/docker-compose.yml up -d      # start (pulls images first time)
docker compose -f otel/docker-compose.yml down       # stop (Jaeger's local copies are lost)
docker logs -f otel-otelcol-1                        # watch received spans
```

| Port | Service |
|------|---------|
| 127.0.0.1:4318 | OTLP/HTTP receiver (collector) |
| 127.0.0.1:4317 | OTLP/gRPC receiver (collector) |
| 127.0.0.1:16686 | Jaeger UI |
| 127.0.0.1:13133 | Collector health endpoint (checked by `shlepa run` before a telemetry batch) |

All ports are bound to localhost only. The pinned Jaeger v2 all-in-one
(`jaegertracing/jaeger:2.9.0`) runs with its embedded default config:
in-memory storage capped at 100,000 traces (oldest evicted first), so
the local debug copy is bounded in RAM and never grows the disk; it is
lost on restart. The durable copy lives in the remote MLflow
experiment — treat Jaeger as a scratch pad, not a store.

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

## Export a batch for LLM analysis (`shlepa trace-export`)

`shlepa run` prints a batch id (`<UTC>-<random>`); the same id tags the
MLflow runs (`batch_id`) and the agent traces (`shlepa.batch_id`). To get
a batch's traces out of the durable MLflow backend:

```bash
uv run --project cli --no-sync shlepa trace-export --batch <batch-id>
# -> tmp/trace-export/<batch-id>/
#    manifest.jsonl  one line per task: task, trace_id, state, tokens, signals
#    traces/<task>.json   full trace dump (spans, attributes, events, I/O)
#    digests/<task>.md    compact timeline + failure signals
#    summary.md           batch totals + aggregated signals
```

`--out <dir>` and `--experiment <name|id>` override the defaults
(`SLEPA_TRACE_EXPERIMENT` or `shlepa-traces`). Non-zero exit with a clear
message when the batch has no traces (async export lag or telemetry was
off).

Recommended workflow for a second (analysis) LLM:

1. feed it `manifest.jsonl` + `digests/*.md` (cheap; one context each);
2. for tasks flagged in the manifest (loop / tool_errors /
   repeated_results signals, or state != OK) pull the full
   `traces/<task>.json`.

The digest's failure signals are computed over the exported spans:
`loop:<tool>:<n>` (>=4 identical name+args calls in a 6-call rolling
window), `tool_errors:<n>`, `repeated_results:<n>`.

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

Body-size limits (checked 2026-08-28 from the dev machine):
- a 10 MB dummy body to `POST /v1/traces` returns `400 Invalid
  OpenTelemetry format` (i.e. it passes the reverse proxy and reaches
  the MLflow app), so the proxy limit is comfortably above 10 MB;
- a 30 MB body produced no `413` from the proxy (the upload simply did
  not finish in time on the narrow VPS link) — no evidence of a limit
  between 10 and 30 MB either.
- TODO (on the VPS): confirm `client_max_body_size` >= 64 MB in nginx
  (or equivalent in the reverse proxy) and record the exact value here;
  see the corresponding backlog issue. A realistic batch of a single
  task is far below this, but long multi-task runs with large tool
  results can grow big.

Retention: no archival policy is configured; archived span payloads keep
tag filtering but lose full-text search.
