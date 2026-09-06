# LLM endpoint embeddings (the "agent's own LLM as embedder" path)

Reviewed: 2026-09-03

The dev LLM endpoint (llama.cpp, OpenAI-compatible) can expose an
embeddings API. This note collects the evidence for how well *LLMs as
embedders* work, and the design limits that decide what is viable for us.

## llama.cpp capabilities (dev endpoint)

- `--embeddings` flag enables embedding generation (server currently
  returns 501 without it — verified 2026-09-03).
- `--pooling {none, mean, cls, last, rank}` selects the pooling of hidden
  states into the final vector.
- OpenAI-compatible `POST /v1/embeddings`; a `POST /reranking`
  (cross-encoder) endpoint also exists.

## Evidence: how good are LLM embeddings?

- **E5-Mistral / "Mistral Embedding"** (arXiv:2401.00368): 7B LLMs
  fine-tuned for embedding (base and instruction-tuned), using
  **last-token pooling**; state-of-the-art at publication. Shows a
  *fine-tuned* LLM's last-token state is a strong embedder.
- **LLM2Vec** (arXiv:2404.05961): turns decoder LLMs into competitive
  embedders via two-stage fine-tuning (bidirectional attention, then
  contrastive alignment). Requires fine-tuning the target model.
- **LLM2Vec-Gen** (arXiv:2603.10913, verified 2026-09-03): self-supervised
  variant producing embeddings in the LLM output space, jointly
  optimizing retrieval and generation with a next-token loss. Also
  training-based.

Common denominator: **all strong LLM-embedding results involve
fine-tuning the LLM.** The quality of a *vanilla* (non-fine-tuned) LLM's
raw hidden states as an embedder is not established by these papers —
that is exactly what experiment E3 (#93) measures, because it is the only
regime we can actually run (we do not own the contest model and have no
fine-tuning infrastructure).

## Design limits (decisive)

1. **Same-model constraint.** Precomputed doc vectors are only meaningful
   if the query side is embedded by the *same* model. "Precompute with a
   big model, query with a small model" is dead.
2. **Startup embedding is over budget.** Embedding the 709 KB rows/cheats
   through a 27B-class endpoint at task start ≈ 2–5 min wall (709 docs,
   sequential or lightly batched) — against a 600 s per-task wall clock.
   Even if it fit, the wall cost is paid on every task.
3. **Contest model unknown.** Doc vectors cannot be precomputed for the
   contest endpoint; the model (and its pooling) is not part of the
   contract.

Consequences:

- Endpoint embeddings are a **dev-only experiment** (E3 in #93): quality
  ceiling for the "the agent's LLM can embed" hypothesis, nothing the
  contest submission can rely on.
- At most an **opportunistic** runtime feature with a graceful fallback to
  BM25 — probe `/v1/embeddings` once at startup, use it if present,
  otherwise stay lexical. Never a dependency.
- The re-query loop (agent re-issues refined queries against the KB tool)
  is the contest-safe form of LLM-in-the-loop retrieval — see
  `notes/hybrid-fusion.md`.

## E3 experiment design (#93)

1. User restarts the dev llama.cpp with `--embeddings` (test `--pooling
   last` per E5-Mistral, and `mean` as a control).
2. Dev script embeds the 709 doc texts (`id name cheat`) once → cached
   JSON (doc vectors are per-model artifacts; never committed to the KB).
3. Embed the 48 queries from `analysis/queries.jsonl`; score with
   `bench.py vectors` (+ `--rrf-k 60` for the hybrid).
4. Record P@1/P@5 (all/paraphrase/literal) and per-call latency.

## Sources

- llama.cpp: https://github.com/ggml-org/llama.cpp (`--embeddings`,
  `--pooling`, `/reranking`).
- E5-Mistral: arXiv:2401.00368 (Wang et al., "Mistral Embedding").
- LLM2Vec: arXiv:2404.05961 (Behnamghader et al.).
- LLM2Vec-Gen: arXiv:2603.10913 (verified via web search 2026-09-03).
- 501 probe of the local endpoint, 2026-09-03.
