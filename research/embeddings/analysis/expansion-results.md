# BM25 + semantic expansion on the shared query set

Reviewed: 2026-09-03

Method: `bench.py bm25 --expansion agent/shlepa_agent/kb/expansion.jsonl` —
the same scoring as the baseline (`bm25-baseline.md`), with the pinned
expansion appended to each BM25 doc text (the `MitreKB(expansion=...)`
hook, issue #94). Artifact: 709 rows of LLM-generated incident-report
paraphrases (2-3 sentences per technique, prompt v1,
`scripts/expand_kb.py`, dev endpoint Qwen3.8-27B-UD-IQ4_XS; 308 KB raw,
+97,785 B zipped). Identity hygiene: 0 T-ID leaks, 0 "MITRE" occurrences.
Per-query rows (with top-5): `bm25-expansion-rows.jsonl`.

## Results (2026-09-03)

| split | n | P@1 (base → +exp) | P@5 (base → +exp) |
|---|---|---|---|
| all | 48 | 20.8% → 20.8% | 33.3% → **50.0%** |
| paraphrase | 40 | 5.0% (2/40) → 5.0% (2/40) | 20.0% (8/40) → **40.0%** (16/40) |
| literal | 8 | 100% → 100% | 100% → 100% |

## Reading

- Paraphrase P@5 doubles: +10 queries gain a top-5 hit (p02, p03, p09,
  p13, p14, p18, p21, p26, p32, p38); 2 regress (p01 want T1047, p31 want
  T1083 — the added incident vocabulary pushed the expected technique out
  of the top-5).
- P@1 is flat at 2/40 with a membership change (loses p07, gains p06).
  The shipped tool returns top-5, so P@5 is the operative metric.
- Literal split holds at 100%: the over-generic-vocabulary regression
  flagged as the failure mode in `fit-matrix.md` did not materialize.
- Beats the C′ mini-256 measured results on the same set (dense 37.5% /
  RRF hybrid 27.5%, `vtx-results.md`) at ~+96 KB static and zero runtime
  cost (no model; same BM25 path).
- Same caveats as the baseline apply: 48-query research set, strict
  sub-technique grading (parent-first = miss), deliberately harsh
  paraphrase split (real agent queries sit between the splits).

## Reproduce

```bash
uv run --project cli --no-sync python research/embeddings/analysis/bench.py bm25 \
    --expansion agent/shlepa_agent/kb/expansion.jsonl \
    --save research/embeddings/analysis/bm25-expansion-rows.jsonl
```
