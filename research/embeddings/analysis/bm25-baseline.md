# BM25 baseline on the shared query set

Reviewed: 2026-09-03

Method: `bench.py bm25` — the shipped tool's scoring (BM25, k1=1.5,
b=0.75, stopword-filtered) over the cheat corpus (`id name cheat` per
row, 709 docs), same tokenizer/params as `agent/shlepa_agent/mitre_kb.py`.
Ground truth: `queries.jsonl` (48 queries, expected T-IDs validated
against `rows.json` + `aliases.json`). Per-query rows (with top-5):
`bm25-baseline-2026-09-03.jsonl`.

## Results (2026-09-03)

| split | n | P@1 | P@5 |
|---|---|---|---|
| all | 48 | 20.8% | 33.3% |
| paraphrase | 40 | 5.0% (2/40) | 20.0% (8/40) |
| literal | 8 | 100% | 100% |

## Reading

- The two failure modes are cleanly separated: literal indicator
  language (process names, API names, encodings) is perfect;
  natural-language incident phrasings almost never get the expected
  technique into the top-5.
- Sample paraphrase misses (see JSONL for all): "an event subscription
  was created in the system's object management infrastructure…" (want
  T1047, got T1546.003/T1059.004 first); "a dormant local account was
  re-enabled and given local administrator rights" (want T1531, no hit);
  "the host protection tool was stopped and its reporting disabled"
  (want T1685 — T1685 made top-5 at rank 4; near-miss pattern).
- Sub-technique strictness: several paraphrases rank the *parent* first
  (e.g., T1053 vs expected T1053.005). This baseline scores those as
  misses (grading string-matches specific IDs); a lenient
  parent/child-inclusive variant is a follow-up measurement.

## Caveats

1. The paraphrase set is deliberately harsh (no deliberate lexical
   overlap with the cheat text). Real agent queries carry some literal
   indicators (process names, ports, file paths), so real-world BM25
   performance is expected *between* the two splits — the 20% P@5 is a
   floor, not a point estimate.
2. Corpus is the cheat text (what the shipped tool uses). BM25 over the
   full `description` field is not measured yet; the description is more
   verbose and may rank sub-techniques differently.
3. 48 queries is a research set, not a benchmark: good enough to
   compare methods against each other, not to publish numbers.

## Reproduce

```bash
uv run --project cli --no-sync python research/embeddings/analysis/bench.py bm25
```
