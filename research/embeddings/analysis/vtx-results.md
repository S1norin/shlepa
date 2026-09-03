# vtx-embed (C′) results on the shared query set

Reviewed: 2026-09-03

C′ experiment (`cprime-protocol.md`) executed 2026-09-03. Models
`VTXAI/vtx-embed-1M` (nano, 64d, 0.93 MB) and `vtx-embed-7M` (mini,
256d, 5.41 MB), MIT; encoding = 4-bit static table → SIF IDF-weighted
mean (fit on the KB corpus) → PC-1 removal (fit on the KB corpus) →
L2 norm. Corpus identical to the BM25 baseline
(`f"{tid} {name} {name} {cheat}"`, 709 docs); queries = the shared
48-query set (`queries.jsonl`). Harness: `vtx_bench.py` +
`bench.py vectors` (RRF k=60).

## Results

Baseline (BM25, `bm25-baseline.md`) first; P@1/P@5 per split.

| method | split | n | P@1 | P@5 |
|---|---|---|---|---|
| **BM25 (baseline A)** | all | 48 | 20.8 | 33.3 |
| | paraphrase | 40 | 5.0 | **20.0** |
| | literal | 8 | **100.0** | **100.0** |
| nano-64 dense | all | 48 | 16.7 | 27.1 |
| | paraphrase | 40 | 7.5 | 15.0 |
| | literal | 8 | 62.5 | 87.5 |
| nano-64 RRF | all | 48 | 20.8 | 35.4 |
| | paraphrase | 40 | 7.5 | **22.5** |
| | literal | 8 | 87.5 | 100.0 |
| mini-256 dense | all | 48 | 18.8 | **47.9** |
| | paraphrase | 40 | 7.5 | **37.5** |
| | literal | 8 | 75.0 | 100.0 |
| mini-256 RRF | all | 48 | 22.9 | **39.6** |
| | paraphrase | 40 | 10.0 | **27.5** |
| | literal | 8 | 87.5 | 100.0 |
| mini-128 (Matryoshka) dense | all | 48 | 10.4 | 37.5 |
| | paraphrase | 40 | 2.5 | 25.0 |
| | literal | 8 | 50.0 | 100.0 |
| mini-128 RRF | all | 48 | **25.0** | **39.6** |
| | paraphrase | 40 | **12.5** | **27.5** |
| | literal | 8 | 87.5 | 100.0 |

Per-query rows (top-5 + hit flags, for failure analysis):
`vtx-nano-rows.jsonl`, `vtx-mini-rows.jsonl`,
`vtx-mini-128-rows.jsonl`.

## Latency and ACP fidelity

- Query encode: **0.02–0.04 ms/query** on the dev host;
  **0.08 ms/query** inside `secureintelligent/acp:latest` (H3:
  trivially within budget — ~8 ms for a hundred lookups per task).
- Build-time SIF+PC fit on the 709-doc corpus: 0.1–0.3 s (one-off,
  pinned in the zip).
- Fidelity: the unmodified `vtx_bench.py` run inside the ACP image
  (numpy + tokenizers, no `safetensors`) produced **byte-identical**
  vectors to the dev run — dev numbers are the runtime numbers.

## Reading (against the protocol's decision matrix)

1. **H1 holds for mini.** Dense-alone paraphrase P@5 **37.5% vs BM25
   20.0%** (+17.5 pt, ~1.9×) — a 4-bit *static* table has genuine
   semantic recall on this corpus. H2/H3 hold (below).
2. **Success bar met by mini-256 RRF.** Paraphrase P@5 27.5%
   (materially above 20.0%), literal P@5 held at 100% (P@1 drops
   100→87.5%, one l-query demoted to #2). Protocol row 1 → C′ is
   worth wiring.
3. **RRF trades paraphrase for literal safety.** Mini dense alone
   (37.5) > hybrid (27.5): BM25's weak paraphrase ranks dilute the
   dense ranking under RRF. The hybrid is the conservative shipping
   choice (protects the 100% literal P@5, best all-split P@5 39.6);
   dense-first/RRF-tuning is a follow-up if paraphrase P@1 matters.
4. **Nano (64d) is marginal.** Hybrid +2.5 pt over baseline — not
   worth 1 MB of zip on its own. 64d is too small; the family works,
   the dimension is the cost.
5. **Matryoshka 128d** costs dense-alone quality (25.0 vs 37.5) but
   keeps the hybrid (27.5) and best P@1 (12.5) — and does **not**
   shrink the model file (truncation is post-dequant), so it buys
   nothing on the zip axis.

## Miss analysis (mini-256 RRF, 29/40 paraphrase misses)

Two classes visible in the JSONL:

- **Sibling sub-technique confusion** — expected T1027.009, got
  T1027.008/T1027.012 in top-5 (p08); expected T1550.002, got
  T1550.004 (p34). The model finds the family, not the sub-technique.
  Fix direction: finer KB rows / sub-technique cheat text, not a
  bigger model.
- **Whole-category misses** — expected T1059.001 (command
  interpreter), got T1564.* (file/decoy) for "hidden console window
  executed a decoded command string" (p04). Fix direction:
  semantic keyword expansion (F, issue #94) — exactly the gap it
  targets.

## Shipping math (unchanged from `notes/vtx-embed.md`)

- **nano**: zip ≈ 5.6 MB, ~4.4 MB spare — but marginal quality.
- **mini**: zip ≈ 10.2 MB → over; fits only if the 1.19 MB
  verbatim-rows fallback is dropped (scope decision) → ≈ 9.1 MB.

## Next steps

1. Scope decision: does the verbatim-rows fallback (1.19 MB) stay or
   go? That is the gate for shipping **mini** (≈ 9.1 MB zip).
2. If yes: wire the mini-256 + RRF path into `mitre_kb.py` as a new
   toolset arm (build-time: `.npy` conversion of the table, pin SIF/PC
   + doc vectors), verify ≤ 10 MB via `shlepa zip`, A/B via
   `shlepa run --arm`.
3. In parallel: semantic keyword expansion (#94) — the miss analysis
   says it attacks the dominant residual class, at ~200 KB instead of
   ~5.4 MB.
4. #93 ceiling (MiniLM-int8 + endpoint) still stands as the quality
   ceiling reference before any distillation (C).

## Artifacts

- vectors (gitignored, regenerable): `vtx-{nano,mini,mini-128}-docs.json`,
  `…-queries.json`; ACP-fidelity copies: `vtx-nano-acp-*.json`
- per-query rows (committed): `vtx-{nano,mini,mini-128}-rows.jsonl`

## Sources

- Protocol: `cprime-protocol.md`; model verification: `notes/vtx-embed.md`
- Baseline: `bm25-baseline.md`; option context: `fit-matrix.md`
- Reference engine (MIT): https://huggingface.co/VTXAI/vtx-embed-7M
