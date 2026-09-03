# C′ experiment protocol: in-zip static embedder (vtx-embed) vs BM25

Reviewed: 2026-09-03
Status: protocol — runs 2026-09-03; results → `vtx-results.md` (new).

What the C′ experiment (fit-matrix recommendation rev 2) measures, how
it runs, and how to read the outcome. Model verification, zip-size math
and risks: `notes/vtx-embed.md`. The baseline being compared against:
`bm25-baseline.md`.

## What we are trying to answer

BM25 — the shipped retrieval path in `mitre_kb.py` — measures
P@5 20.0% on paraphrase incident phrasings and 100% on literal
indicator phrasings (`bm25-baseline.md`). Option C′ is the cheapest
possible dense path: a ~1 MB *static* embedder in the zip, no training,
no ONNX. The hypotheses:

- **H1 — semantic recall.** A 4-bit static SIF embedder recovers
  enough synonym recall to lift paraphrase P@5 materially above 20%.
- **H2 — hybrid floor.** RRF fusion (BM25 rank + dense rank, k=60)
  beats both singles and never regresses the literal split, where
  BM25 already scores 100%.
- **H3 — runtime cost.** A static table lookup (no forward pass) is
  cheap enough to run on every KB query inside the 600 s task clock.

## How it runs

1. **Corpus — identical to BM25.** The 709 ATT&CK rows
   (`kb/rows.json` + `cheats.jsonl`) with doc text
   `f"{tid} {name} {name} {cheat}"` — exactly the string the BM25 index
   ranks, so dense and baseline numbers are directly comparable (no
   corpus mismatch).
2. **Models.** `VTXAI/vtx-embed-1M` (nano: 64d, 0.93 MB) and
   `vtx-embed-7M` (mini: 256d, 5.41 MB), MIT license. Loaded by the
   dependency-free reader in `vtx_bench.py` (the ACP image has no
   `safetensors` package). Encoding pipeline (verbatim from the
   reference engine, MIT): tokenize → 4-bit dequantize →
   IDF-weighted token mean (SIF, a=0.05) → PC-1 direction removal →
   L2 normalize. The IDF weights and PC-1 direction are **fit on the
   KB corpus** (corpus-adaptive) and pinned afterwards — that fit is
   build-time work, not runtime.
3. **Queries.** The shared 48-query ground-truth set
   (`queries.jsonl`: 40 paraphrase + 8 literal, expected T-IDs
   validated against the KB) — the same set as the BM25 baseline.
4. **Scoring.** `bench.py vectors`: dense P@1/P@5 and RRF-hybrid
   P@1/P@5 per split (all / paraphrase / literal); per-query top rows
   saved to JSONL for failure analysis.
5. **Runs.** nano (64d native); mini (256d native **and** 128d
   Matryoshka-truncated — isolates dimension from model family).
   Per-query encode latency is reported (dev host as ACP-CPU proxy).
6. **ACP fidelity.** The same `vtx_bench.py` runs unmodified inside
   `secureintelligent/acp:latest` (numpy + tokenizers only), so dev
   numbers are runtime numbers (exact docker command in the
   `vtx_bench.py` docstring).

Working-tree note: the bench imports `mitre_kb.py` + `kb/`, which live
on PR #77 (`feature/forensics-toolset-arm`), not on this branch. They
are checked out temporarily for the run and are **not** part of the
experiment or of any commit here.

## What the results are

One table row per (model × dimension) × (dense / RRF hybrid) ×
(all / paraphrase / literal) split, next to the BM25 baseline:
`vtx-results.md`. Alongside: per-query encode latency (ms/query),
fitted-artifact sizes (SIF + PC bytes, for the zip math), and the list
of queries the hybrid still misses (JSONL) — the failure analysis that
tells us whether the remaining gap is composition/negation (a static
limitation) or coverage (fixable by expansion, #94).

Not measured here: MTEB or other external benchmarks (self-reported
numbers only; our query set is the decision input), and task-level
agent scoring (that comes after wiring, via `shlepa run`).

## How to read the results

| outcome (RRF hybrid vs BM25 baseline) | reading | next step |
|---|---|---|
| paraphrase P@5 materially > 20%, literal preserved | H1+H2 hold — static embeddings close a measurable part of the gap | wire C′ into `mitre_kb.py` (new toolset arm), verify zip ≤ 10 MB via `shlepa zip`, update fit-matrix recommendation |
| paraphrase P@5 ≈ 20%, literal preserved | the static table adds no semantic signal beyond BM25 on this corpus | drop C′ from shipping; keep A + F (keyword expansion, #94); let the #93 ceiling decide whether distillation is worth it |
| hybrid < baseline on the literal split | always-on fusion hurts the strong side | use dense as fallback (rank only when BM25 score is low), not as a standing fusion |
| nano ≪ mini on paraphrase | 64d is too small; family is fine | scope decision: mini fits only if the 1.19 MB verbatim-rows fallback is dropped (fit-matrix note) |

Expected failure modes if H1 holds only partially (static =
distributed bag-of-words, so word order, negation and sub-technique
distinction are the weak spots): the JSONL miss list should show which
class dominates — if it is "wrong sub-technique" the fix is finer KB
rows, not a bigger model.

**Success bar:** RRF-hybrid paraphrase P@5 materially above 20.0%
without regressing the literal split.
