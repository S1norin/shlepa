# vtx-embed (Vortex-Embed): 4-bit static embedding models

Reviewed: 2026-09-03 (files pulled from HF, code read in full)

`VTXAI/vtx-embed-7M` ("mini") and `VTXAI/vtx-embed-1M` ("nano") —
MIT-licensed, ultra-lightweight **static** sentence-embedding models
powering the [vortexa](https://github.com/OEvortex/vortexa) codebase
search engine. Discovered via an external finding (2026-09-03) and
verified file-by-file; this is the only retrieval-grade embedder found
so far that can fit our zip headroom.

## Verified facts (HF API + code read, 2026-09-03)

| | `vtx-embed-7M` (mini) | `vtx-embed-1M` (nano) |
|---|---|---|
| params | 7.56M | 1.05M |
| weights (`model.safetensors`) | 4,724,744 B (4.72 MB) | 786,688 B (0.75 MB) |
| `tokenizer.json` | 683,666 B (0.68 MB) | 375,922 B (0.36 MB) |
| **total** | **5.41 MB** | **0.93 MB** |
| dims | 256 (Matryoshka → 128/64) | 64 (Matryoshka) |
| vocab | 29,528 | 16,384 |
| quantization | LF4 (4-bit per 32-block, FP16 scale+zero) | same |
| license | MIT | MIT |

Self-reported (author's card; no paper, no independent replication):
mini STS 0.7918 / SICK-R 0.6294 / Banking77 0.7043; nano STS 0.7149 /
SICK-R 0.5916 / **Banking77 0.8384** / Amazon-Counterfactual 0.7731
(nano beats mini on the classification tasks — the task type closest to
query→technique mapping).

## How it works (from `vortex_embed_v4_5.py`, read in full)

- Static token-embedding table (4-bit packed) → per-token dequantize →
  **SIF pooling** (Arivazhagan et al. 2016): IDF-weighted mean with
  PC-1 removal → optional Matryoshka truncation → L2 normalize.
  No transformer forward pass: encode = tokenize + gather + weighted
  mean. Sub-millisecond per sentence on CPU is plausible (unmeasured in
  ACP yet).
- **Corpus-adaptive**: `fit_idf(corpus)` and `fit_pc(corpus_embs)` are
  called on the indexed corpus. For us: fit on the 709 KB rows/cheats
  at build time, pin the fitted `sif_weights` (16k–29k floats) + one PC
  direction. IDF then reflects the ATT&CK domain, not whatever corpus
  the author used.
- Dependencies: `numpy`, `tokenizers` (both preinstalled in ACP),
  `safetensors` (NOT in ACP — but the weights are three flat tensors;
  convert to `.npy` at build time, or read the trivial safetensors
  header with ~25 lines of numpy code). `huggingface_hub` only for
  `from_pretrained` by repo id (dev path; we ship files in-zip).

## Zip fit (vs 5.65 MB headroom, current zip 4.57 MB)

| variant | payload | projected zip | fits? |
|---|---|---|---|
| nano + sif (≈30 KB) + 709×64d int8 vectors (≈45 KB) + code (≈10 KB) | ≈ 1.0 MB | ≈ 5.6 MB | **yes, ~4.4 MB spare** |
| mini + sif (≈120 KB) + 709×128d int8 vectors (≈90 KB) | ≈ 5.6 MB | ≈ 10.2 MB | **no** — over by ~200 KB |
| mini, if the opt-in (a) verbatim-rows fallback (1.19 MB) is dropped | ≈ 5.6 MB | ≈ 8.9 MB | yes, with a scope decision |

## Risks / open questions

- Single-author 2026 project, benchmarks self-reported, no paper, no
  third-party evaluation. The inference code itself is clean
  (numpy-vectorized, no suspicious imports, no network calls).
- Static embeddings = distributed bag-of-words: strong on synonym
  recall ("protection tool stopped" ~ "endpoint protection agent
  terminated"), weak on word order/negation/composition and
  sub-technique distinctions. Exactly complementary to BM25 — measure,
  don't assume.
- Tokenizer is an HF fast tokenizer (BPE, 29.5k/16.4k vocab) — English
  code-ish text; OOV handling = existing BPE fallback, fine.

## Test plan (bench-ready)

1. Download both variants (user action, ~6.3 MB) into
   `tmp/vtx-embed/{mini,nano}/`.
2. `analysis/vtx_bench.py`: load model + tokenizer, `fit_idf`/`fit_pc`
   on the KB corpus, encode 709 doc texts + 48 queries, emit vectors
   JSONs.
3. `bench.py vectors --doc-vectors … --query-vectors … --rrf-k 60` →
   P@1/P@5 (all/paraphrase/literal) + RRF hybrid vs the BM25 baseline
   (`analysis/bm25-baseline.md`).
4. Also time per-query encode latency on this host (proxy for ACP CPU).

## Sources

- https://huggingface.co/VTXAI/vtx-embed-7M (+ `-1M`) — files pulled and
  code read 2026-09-03; sizes via resolve-URL `content-length`.
- https://github.com/OEvortex/vortexa — engine integration.
- SIF: Arivazhagan et al., "Simple and Effective Approaches to
  Developing Generative Models" (ICLR 2018, the SIF pooling origin:
  "Linguistic Regularities in Simple Neural Language Models", EACL 2016).
- External finding text (2026-09-03) that surfaced the model; its other
  claims, verified 2026-09-03: jina-code-embeddings-0.5b = 494M params
  (https://jina.ai/models/jina-code-embeddings-0.5b/ — confirmed); code
  and cybersecurity embedders are all ≥100M params or domain-mismatched
  (the finding's "~41 MB cyber BERT" was unsourced — `unverified`);
  `axiotic/ogma-micro` real but 8.9 MB (> 5.65 MB headroom) with
  self-reported "52.18 MTEB" from a private 66-task run; Ternlight real
  but 7 MB WASM-targeted (over budget, browser-oriented);
  `kekeappa/kor-static-embedding-64` real but Korean-only (KLUE/KorSTS);
  OGL-Mini ("Open Guard Layer") real but an agent **input-screening**
  guard model, not a retrieval embedder — no use for us.
