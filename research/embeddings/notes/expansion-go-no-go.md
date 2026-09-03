# GO/NO-GO: BM25 semantic expansion (issue #94)

Reviewed: 2026-09-03

Single subject: does the pinned LLM-generated expansion
(`agent/shlepa_agent/kb/expansion.jsonl`, 709 rows, prompt v1) justify
shipping the `MitreKB(expansion=...)` hook as the default KB corpus?

## Numbers vs baseline

BM25 vs BM25+expansion on the shared 48-query set (full table and
per-query rows: `analysis/expansion-results.md`):

- paraphrase P@5: 20.0% → **40.0%** (doubles; above C′ mini-256's dense
  37.5% and RRF 27.5% on the same set, `analysis/vtx-results.md`)
- literal P@5: 100% → 100% (held; the over-generic-vocabulary regression
  risk did not materialize)
- P@1: 5.0% → 5.0% (flat; top-5 is the operative metric for the tool)
- size: +97,785 B zipped (4,572,574 → 4,670,359, ~+2.1%), ≪ 10 MB;
  runtime cost zero (static corpus text, same BM25 path, no model, no
  new dependencies)

## Decision: GO

Adopt the expansion as part of the KB corpus. The success bar was
"approach the C′ mini-256 dense result (paraphrase P@5 37.5%) at ~+0.3 MB
static, zero runtime cost"; measured 40.0% at ~+96 KB static.

## Follow-up (separate PR, gated by this note)

- Wire the artifact into the shipped loader: add `expansion.jsonl` to
  `kb_meta.json` `files` (bytes + sha256, like the other pinned files)
  and load it in `get_kb()` so the expansion is on by default.
- Task-level A/B: baseline vs expansion arm via `shlepa run --arm` to
  confirm the retrieval gain survives contact with real tasks.

Known limits (carried, not blocking): P@1 unchanged; 2/40 paraphrase
queries regressed in top-5 (p01 T1047, p31 T1083); 48-query research set.
