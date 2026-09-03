# Fit matrix: semantic retrieval options for the MITRE KB

Reviewed: 2026-09-03

Constraints recap (`research/embeddings/README.md`): offline ACP runtime
with preinstalled `onnxruntime`/`numpy`/`tokenizers`, **5.65 MB zip
headroom**, 600 s task wall clock, chat-only contest endpoint, ~300K
token budget. Baseline to beat: option A's measured numbers
(`bm25-baseline.md`).

## Options

| # | option | zip cost | runtime deps | query latency | expected quality | effort | risk |
|---|---|---|---|---|---|---|---|
| A | BM25 only (status quo) | 0 | stdlib | ~0 ms | measured: P@5 20% paraphrase / 100% literal | done | — |
| B | in-zip off-the-shelf ONNX model | ≥ 23 MB | onnxruntime | ~50–150 ms (est.) | MiniLM-class | — | **infeasible** — no ≤5 MB model exists (`notes/small-models.md`) |
| C | in-zip **distilled ~3 MB** model | ~1.5–3 MB | onnxruntime | ~50–150 ms (est.) | unknown, ≤ MiniLM | high (dev-time torch training + eval) | medium — quality unproven |
| **C′** | in-zip **`vtx-embed-1M`** (static SIF, LF4 4-bit, MIT — `notes/vtx-embed.md`) | **≈ 1.0 MB** (model 0.75 + tokenizer 0.36 + fitted SIF/PC + int8 doc vectors + code) | numpy + tokenizers (both in ACP; `safetensors` absent → build-time `.npy` conversion) | measured 0.02–0.08 ms/query (dev/ACP) | **measured 2026-09-03**: mini-256 dense paraphrase P@5 37.5% / RRF 27.5% (vs BM25 20.0%), literal held; nano-64 marginal (RRF 22.5%) — `analysis/vtx-results.md` | **low** (no training; ~1 day: port loader, fit SIF on KB, bench, wire into `mitre_kb`) | medium — self-reported benchmarks, single-author project |
| D | dev-only MiniLM-int8 arm (SIFS pattern, cf. #57) | 0 (dev image only) | onnxruntime (in ACP) | measured in #93 | MiniLM-class | low | low — A/B only, never ships |
| E | endpoint `/v1/embeddings` | 0 | endpoint only | per endpoint | unknown (vanilla LLM) | low (user restarts llama.cpp) | **high** — contest contract undocumented; startup embedding of 709 docs ≈ 2–5 min > 600 s wall |
| F | **semantic keyword expansion** (LLM-generated paraphrases merged into BM25 corpus, build-time) | ~+200 KB | stdlib | ~0 ms | unknown — directly targets the measured gap | medium (generator script + artifact pinning) | low — pure corpus data, same runtime path as A |

Notes: `vtx-embed-7M` (mini, 5.41 MB) does **not** fit with the current
zip (projected ≈ 10.2 MB); it fits only if the opt-in (a) verbatim-rows
fallback (1.19 MB) is dropped — a scope decision. `vtx-embed-1M` (nano) fits
with ~4.4 MB spare. AST/tree-sitter chunking (from the same external
finding) is N/A: our corpus is 709 flat JSON rows, and the ACP image has
no tree-sitter.

Vector storage cost if a model ships in-zip (C): 709 docs × 384d =
1.09 MB fp32 / 0.55 MB fp16 / 0.27 MB int8 — the weights, not the
vectors, are the cost.

## Recommendation (2026-09-03, rev 3 after C′ measurement)

1. **C′ measured first (#93, added) — DONE 2026-09-03.** Result
   (`analysis/vtx-results.md`): mini-256 **meets the success bar** —
   RRF hybrid paraphrase P@5 27.5% (dense alone 37.5%) vs BM25 20.0%,
   literal P@5 held at 100%; nano-64 is marginal (+2.5 pt) and not
   worth the 1 MB alone. Next gate: scope decision — mini (5.41 MB)
   fits the zip only if the 1.19 MB verbatim-rows fallback is dropped
   (→ ≈ 9.1 MB); then wire mini-256 + RRF into `mitre_kb.py` as a
   toolset arm and A/B via `shlepa run --arm`.
2. **Run F in parallel (#94).** No-model BM25-side improvement;
   complementary to C′ (corpus data vs vector model) — both can ship.
3. **Run D+E as the quality ceiling (#93), dev-only.** MiniLM-int8
   answers "how far above can a real transformer get"; if the ceiling is
   barely above C′+F, stop there. E probes the vanilla-LLM-endpoint
   hypothesis (unverified — `notes/endpoint-embeddings.md`).
4. **C (distillation) only if the ceiling is far above C′+F** — now a
   genuine stretch, since C′ ships without any training.
5. **E never ships as a dependency** (chat-only contest contract).
6. **Keep exact-ID-first + alias resolution as stage 0** in every option
   (graders string-match IDs, old included).

## What would change this

- ~~C′ measured below baseline~~ — measured 2026-09-03 **above**
  baseline (mini-256, `analysis/vtx-results.md`); the live gate is now
  the zip-fit scope decision (verbatim-rows fallback) and the task-level
  A/B (`shlepa run --arm`) after wiring.
- The ACP image drops `tokenizers` or `numpy` → C′ breaks; re-verify
  `notes/runtime-capabilities.md`.
- The ACP image changes (torch added, or zip budget raised) → re-run the
  size/feasibility analysis in `notes/small-models.md`.
- The contest documents an embeddings endpoint with a stable model →
  re-evaluate E as a first-class option (still no precomputed vectors:
  the model may change between contests).
- #94 shows expansion regresses the literal split (over-generic
  vocabulary) → fall back to A until a better expansion prompt exists.

## Sources

- `notes/runtime-capabilities.md`, `notes/small-models.md`,
  `notes/endpoint-embeddings.md`, `notes/hybrid-fusion.md`,
  `analysis/bm25-baseline.md` (all 2026-09-03).
- SIFS dev-arm precedent: issue #57.
