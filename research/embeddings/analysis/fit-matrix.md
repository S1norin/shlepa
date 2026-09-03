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
| D | dev-only MiniLM-int8 arm (SIFS pattern, cf. #57) | 0 (dev image only) | onnxruntime (in ACP) | measured in #93 | MiniLM-class | low | low — A/B only, never ships |
| E | endpoint `/v1/embeddings` | 0 | endpoint only | per endpoint | unknown (vanilla LLM) | low (user restarts llama.cpp) | **high** — contest contract undocumented; startup embedding of 709 docs ≈ 2–5 min > 600 s wall |
| F | **semantic keyword expansion** (LLM-generated paraphrases merged into BM25 corpus, build-time) | ~+200 KB | stdlib | ~0 ms | unknown — directly targets the measured gap | medium (generator script + artifact pinning) | low — pure corpus data, same runtime path as A |

Vector storage cost if a model ships in-zip (C): 709 docs × 384d =
1.09 MB fp32 / 0.55 MB fp16 / 0.27 MB int8 — the weights, not the
vectors, are the cost.

## Recommendation (2026-09-03)

1. **Run F next (#94).** Cheapest contest-viable semantic improvement:
   no runtime change, ~200 KB, and it attacks exactly the measured gap
   (BM25 fails where the query text has no lexical overlap with the
   cheat — LLM-generated paraphrases add precisely that overlap at
   build time). Success criterion: paraphrase P@5 materially above 20%
   without regressing the literal split.
2. **Run D+E in parallel as the ceiling measurement (#93), dev-only.**
   Answers "how good can dense get for us" (MiniLM-class and
   vanilla-LLM endpoints) before any in-zip investment. E additionally
   probes whether the dev llama.cpp's raw vectors carry paraphrase
   signal at all (unverified hypothesis — see `notes/endpoint-embeddings.md`).
3. **C only if the ceiling justifies it.** If dense P@5 ≫ A+F P@5 on the
   paraphrase split, a distilled ~3 MB student becomes the
   contest-shippable hybrid (RRF fusion per `notes/hybrid-fusion.md`).
   If the ceiling is only marginally above A+F, distillation buys
   nothing and we stay on A(+F).
4. **E never ships as a dependency.** At most an opportunistic startup
   probe with graceful BM25 fallback (chat-only contract; unknown
   contest model).
5. **Keep exact-ID-first + alias resolution as stage 0** in every option
   (graders string-match IDs, old included).

## What would change this

- An off-the-shelf ≤ 5 MB high-quality embedder appears → re-open B.
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
