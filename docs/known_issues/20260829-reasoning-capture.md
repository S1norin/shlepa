# Reasoning capture gap in pre-v1 traces

Date first observed: 2026-08-29

## Symptom

Some of the oldest agent traces in the `shlepa-traces` experiment have
LLM spans with **no** `gen_ai.output.messages` and **no** token usage
attributes (`gen_ai.usage.*` / `llm.token_count.*`) at all. For those
traces the reasoning (thinking) content is unknowable and token counts
export as 0. `shlepa trace-export` shows `thinking_parts: n/a (no output
messages)` in the digest and flags the `messages_missing` signal in the
manifest — deliberately distinct from (and never co-emitted with)
`no_thinking`.

Verified example: `tr-229800636e040f92a39bb12855b268bf` (request time
2026-08-27 23:53 UTC / 2026-08-28 06:53 local) — 3 spans, the chat span
carries neither messages nor usage.

## Repro

```bash
uv run --project cli --no-sync shlepa trace-export --batch <old-batch-id>
# digests/<task>.md -> "- thinking_parts: n/a (no output messages)"
# manifest.jsonl   -> "messages_missing" in signals
```

Or open a gap-era trace in the MLflow trace UI and note the LLM span has
no typed output messages and no usage attributes.

## Impact

Traces from the earliest days of telemetry (late 2026-08-27 through the
morning of 2026-08-28, around the v1 core rollout at 2026-08-28 20:00
local, commit ab8a3ce) may lack reasoning data and token counts. For
those runs the question "did the model reason, and why did it fail?"
cannot be answered; only later traces support that analysis. The gap is
**partial** — some pre-rollout runs (e.g. the golden fixture span
`cli/tests/fixtures/llm_span_real.json`, captured 2026-08-28 07:18
local) already carry typed output messages — so the timestamp alone is
not authoritative; trust the per-trace signals.

Two distinct situations for new runs, correctly separated by the
signals:

- endpoint started without `--reasoning on` (or a non-reasoning model)
  -> messages are captured but have zero thinking parts ->
  `no_thinking`;
- gap-era instrumentation -> no typed output messages at all ->
  `messages_missing`.

Server-side requirement for full capture: the LLM endpoint must run with
`--reasoning on` and serve a reasoning-capable model (the dev endpoint,
Qwen3.8-27B on :11434, does).

## Workaround

- For gap-era traces: accept that reasoning (and token counts) are
  unknowable; compare such runs only qualitatively.
- For new runs: none needed. With `SLEPA_OTEL_ENABLED=1` every LLM span
  carries typed output messages (with thinking parts when the endpoint
  returns reasoning); the MLflow trace UI Output panel shows
  `<thinking>...</thinking>` + the answer (dev-only enrichment, #40);
  `shlepa trace-export` reports `thinking_parts: N` plus the
  `no_thinking` / `messages_missing` signals (#41).
- Where reasoning lives: `gen_ai.output.messages` thinking parts (raw),
  the MLflow trace UI Output panel (enriched), Jaeger span details, and
  `traces/<task>.json` from trace-export. See the "Reasoning capture"
  section of otel/README.md.

Related issues: #38 (family experiments), #39 (run<->trace link), #40
(span Output enrichment), #41 (digest/manifest signals), #42
(documentation).
