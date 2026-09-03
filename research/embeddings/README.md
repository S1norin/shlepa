# Embeddings & semantic search (research)

Context, hard constraints, and current state of the question: *can we add
semantic search to the MITRE KB RAG (`agent/shlepa_agent/mitre_kb.py`)?*

This area re-opens the dense-embeddings question that
`research/notes/mitre-rag-decision.md` previously rejected (option C,
"dense embeddings"). That rejection rested on "no torch → pure Python too
slow"; it is **invalidated** because the ACP image turns out to
preinstall `onnxruntime` — quantized ONNX inference works with zero new
dependencies. The question is now: what is the best semantic retrieval
under the real constraints, and is any of it worth the zip cost?

## Hard constraints (verified 2026-09-03)

| constraint | value | evidence |
|---|---|---|
| runtime | `secureintelligent/acp:latest`, fully offline, no internet | `research/code_search/README.md` |
| python | 3.12.13 in `/app/.venv` (242 packages) | `notes/runtime-capabilities.md` |
| preinstalled (usable) | `onnxruntime 1.27.0`, `numpy 2.5.0`, `tokenizers 0.23.1`, `chromadb 1.1.1`, `openai 2.44.0`, `tiktoken 0.13.0` | `notes/runtime-capabilities.md` |
| absent | `torch`, `transformers`, `sentence-transformers`, `scikit-learn` | `notes/runtime-capabilities.md` |
| zip budget | ≤ 10 MB; current submission 4.57 MB → **~5.65 MB headroom** | `shlepa zip` |
| task limits | ~300K agent tokens, 600 s wall clock per task | contest rules, `agent/shlepa_agent/config.toml` |
| contest LLM endpoint | chat-only contract; `/v1/embeddings` **undocumented** | contest docs |

Consequence: no off-the-shelf embedding model fits the zip (smallest
usable is 23 MB, `notes/small-models.md`). Any dense runtime path must be
a custom-distilled ~3 MB model or a model pulled into the dev image only
(the SIFS dev-arm pattern, issue #57).

## Master index

| file | subject |
|---|---|
| `notes/runtime-capabilities.md` | what the ACP image actually preinstalls (docker-verified); dev/contest endpoint behavior |
| `notes/small-models.md` | small embedding model landscape: sizes, licenses, MTEB; why nothing ≤ 5 MB exists |
| `notes/endpoint-embeddings.md` | LLM-endpoint embeddings (llama.cpp, E5-Mistral, LLM2Vec): evidence, design limits, contest risk |
| `notes/hybrid-fusion.md` | RRF fusion and when dense actually helps BM25 (TechniqueRAG evidence) |
| `notes/vtx-embed.md` | `VTXAI/vtx-embed-{7M,1M}`: 4-bit static (SIF) embedders, MIT, the only retrieval-grade models found that fit the zip |
| `analysis/queries.jsonl` | shared ground-truth query set (40 paraphrase + 8 literal, expected T-IDs) |
| `analysis/bench.py` | harness: scores BM25 / dense / RRF on the query set (dev-only) |
| `analysis/bm25-baseline.md` | BM25 baseline results (2026-09-03) |
| `analysis/cprime-protocol.md` | C′ experiment protocol: hypotheses, run steps, decision matrix for reading the results |
| `analysis/fit-matrix.md` | cross-cutting option comparison + recommendation |

## Decision record (2026-09-03)

1. **The old rejection is void.** Dense inference is runtime-feasible in
   the ACP image (onnxruntime preinstalled, zero new deps) —
   `notes/runtime-capabilities.md`.
2. **The semantic gap is real.** BM25 on the cheat corpus: P@5 20.0% on
   paraphrase queries vs 100% on literal indicator queries —
   `analysis/bm25-baseline.md`.
3. **No off-the-shelf in-zip model exists.** The smallest usable ONNX
   embedder is 23 MB; an in-zip dense path requires a custom ~3 MB
   distilled model (stretch, gated on the ceiling measurement) —
   `notes/small-models.md`.
4. **Endpoint embeddings are dev-only.** The contest contract is
   chat-only; embedding 709 docs at startup takes 2–5 min on a 27B-class
   endpoint (> 600 s task timeout); the contest model's embeddings are
   unknown, so doc vectors cannot be precomputed. Never a contest
   dependency — `notes/endpoint-embeddings.md`.
5. **Recommendation (rev 2, 2026-09-03).** Keep the contest core
   (exact-ID-first + BM25 + agent re-query loop). The vtx-embed
   verification (`notes/vtx-embed.md`) adds a first option: **C′ —
   `vtx-embed-1M` in-zip (≈ 1.0 MB, numpy+tokenizers only, no training)**,
   measured on the query set first. In parallel: semantic keyword
   expansion (issue #94) and the MiniLM-int8 + endpoint ceiling
   (issue #93); distillation only if the ceiling far exceeds C′+F.
   Detail and gating: `analysis/fit-matrix.md`; measurement protocol
   (what/how/decision matrix): `analysis/cprime-protocol.md`.

Experiments are tracked as GitHub issues: **#93** (ceiling: ONNX +
endpoint vs BM25), **#94** (semantic keyword expansion).
