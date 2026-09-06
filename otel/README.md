# otel/ — local telemetry stack (collector + Jaeger + MLflow)

Local OpenTelemetry pipeline for `shlepa-agent` traces. The collector
**dual-exports** every trace:

```
agent (OTLP) --> otelcol (localhost:4318 http / 4317 grpc)
                   |---> Jaeger (UI :16686, local debugging, in-memory <= 100k traces)
                   +----> remote MLflow server (durable backend, OTLP/HTTP)
```

The MLflow exporter is stateless transport only. Credentials live in
`otel/.env` (gitignored; see `otel/.env.example`), while the CLI routes each
trace to the same family experiment as its MLflow run.

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
- The agent supplies `x-mlflow-experiment-id` for every task, using the
  numeric ID of the family experiment where its MLflow run was created.
  The Collector preserves that request metadata while batching and forwards
  it to MLflow. Credentials remain collector-only.

The exporter targets `https://mlflow.sinorin.ru` and appends the OTLP
signal path `/v1/traces` itself (MLflow 3.6+ OTLP ingestion; the server
runs 3.15.x). Compression: gzip. After changing `otel/.env`, restart the
collector (`docker compose -f otel/docker-compose.yml restart otelcol`).

## Send a test span

One-liner from the repo root (uses the agent's own telemetry module, so it
exercises the exact same exporter path as a real run):

```bash
SLEPA_OTEL_ENABLED=1 OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
  OTEL_EXPORTER_OTLP_HEADERS=x-mlflow-experiment-id=EXPERIMENT_ID \
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
uv run --project cli --no-sync python otel/check_trace.py \
  --backend mlflow --experiment contest
# OK: trace tr-... (N spans, LLM span with token usage, task attribute present)
```

Pass the run's family experiment with `--experiment`, or set
`SLEPA_TRACE_EXPERIMENT`. Only traces tagged `service.name=shlepa-agent` are
considered. The collector exports to the remote server asynchronously, so
give it a few seconds after the run finishes.

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

By default, the exporter discovers family experiments from MLflow runs tagged
with the batch ID and also checks the legacy trace experiment. Use
`--experiment <name|id>` to restrict the search. It exits non-zero with a
clear message when the batch has no traces (async export lag or telemetry was
off).

Recommended workflow for a second (analysis) LLM:

1. feed it `manifest.jsonl` + `digests/*.md` (cheap; one context each);
2. for tasks flagged in the manifest (loop / tool_errors /
   repeated_results signals, or state != OK) pull the full
   `traces/<task>.json`.

The digest's failure signals are computed over the exported spans:
`loop:<tool>:<n>` (>=4 identical name+args calls in a 6-call rolling
window), `tool_errors:<n>`, `repeated_results:<n>`, `tokens_missing`
(LLM spans with no usage attributes, e.g. an unfinished call),
`no_thinking` (typed output messages captured, zero thinking parts) and
`messages_missing` (no typed output messages at all; the two thinking
signals are mutually exclusive — see "Reasoning capture" below).

## What spans carry

pydantic-ai instrumentation emits spans with OpenAI Inference (`gen_ai.*`)
attributes: model name, token usage, prompt/completion content, tool calls
(bash/read_file/apply_diff/append_file) and their results. Service resource:
`service.name=shlepa-agent`, `service.version=<agent version>`. MLflow runs
created by `shlepa run` get a `trace_ref` tag pointing at this Jaeger when
`SLEPA_OTEL_ENABLED=1`.

## Reasoning capture (thinking parts)

The dev endpoint (llama.cpp, Qwen3.8-27B on :11434) runs with
`--reasoning on` and `--chat-template-kwargs {"preserve_thinking": true}`,
so the model's reasoning stream comes back as OpenAI `reasoning_content`
and the instrumentation records it as `type: "thinking"` parts inside the
LLM span's `gen_ai.output.messages` attribute (next to `text` /
`tool_call` parts).

Where reasoning shows up:

| Surface | What you see |
|---|---|
| `gen_ai.output.messages` on each LLM span (Jaeger span details, `traces/<task>.json` from trace-export) | typed parts incl. the full thinking content |
| MLflow trace UI, span **Output** panel | `<thinking>...</thinking>` + the final answer — a dev-only exporter wrapper rewrites `output.value` / `mlflow.spanOutputs` before OTLP export (#40) |
| `shlepa trace-export` | digest header line `thinking_parts: N` (or `n/a (no output messages)`); manifest signals `no_thinking` / `messages_missing` (#41) |

Signals (mutually exclusive by design):

- `no_thinking` — typed output messages **are** captured but contain
  zero thinking parts: the endpoint/model did not reason (`--reasoning`
  off, or a non-reasoning model).
- `messages_missing` — the LLM spans carry no `gen_ai.output.messages`
  at all (pre-capture-era traces, below): "no thinking" is unknowable,
  so `no_thinking` is **not** emitted alongside it.

Server-side requirement for new runs: the LLM endpoint must be started
with `--reasoning on` and serve a reasoning-capable model; otherwise LLM
spans carry zero thinking parts and the manifest gets `no_thinking`.

Pre-v1 gap: the oldest traces (late 08-27 through the morning of 08-28,
around the v1 core rollout on 2026-08-28 20:00 local, commit ab8a3ce)
may carry **no** `gen_ai.output.messages` and **no** token usage
attributes at all — those runs were tracked without reasoning (and
without token counts); example
`tr-229800636e040f92a39bb12855b268bf` (08-28 06:53 local). The digest
shows `thinking_parts: n/a` and the manifest flags `messages_missing`.
The gap is partial — some pre-rollout runs (e.g. the golden fixture span
`cli/tests/fixtures/llm_span_real.json`, 08-28 07:18 local) already
carry typed output messages — so the timestamp is **not** authoritative:
trust the per-trace signals. Details:
docs/known_issues/20260829-reasoning-capture.md.

Related: #38 (family experiments) · #39 (run↔trace link) · #40 (span
Output enrichment) · #41 (digest signals) · #42 (this documentation).

## Remote MLflow backend (live)

The remote MLflow server (3.15.x) accepts OTLP/HTTP ingestion at
`POST /v1/traces` (basic auth + `x-mlflow-experiment-id` header). The local
collector forwards every trace there, so the remote server is the durable
backend: each MLflow run and its agent trace live in the same family
experiment, correlated by the `batch_id` run tag and the
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
