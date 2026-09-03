# Small embedding models: landscape and zip fit

Reviewed: 2026-09-03

Question: is there an off-the-shelf embedder small enough for the
**~5.65 MB zip headroom** (`research/embeddings/README.md`)? Answer:
**no** — every usable off-the-shelf model is ≥ 23 MB in its smallest
shipped form.

## Candidates (file sizes verified via HF API, 2026-09-03)

| model | params | smallest usable form | size | MTEB (card-reported) | license | fits zip? |
|---|---|---|---|---|---|---|
| `all-MiniLM-L6-v2` | 22.7M | int8 ONNX (`TrendHD/all-MiniLM-L6-v2-int8`) | **23.0 MB** | ~63 avg | Apache-2.0 | no (4× over) |
| `paraphrase-TinyBERT-L6-v2` | ~66M (not "tiny") | fp32 ONNX | 265 MB | ~61 avg | Apache-2.0 | no |
| `bge-small-en-v1.5` | 33M | fp16 (computed) | ~66 MB | ~62 avg | MIT | no |
| `gte-small-en-v1.5` | 33M | fp16 (computed) | ~66 MB | ~62 avg | Apache-2.0 | no |
| `mxbai-embed-small` | 33.5M | fp16 (computed) | ~67 MB | ~61 avg | MIT | no |
| `nomic-embed-text-v1.5` | 137M | fp16 (computed) | ~274 MB | ~63.4 avg | Apache-2.0 | no |
| `Qwen3-Embedding-0.6B` | 600M | ONNX (`Qdrant/Qwen3-Embedding-0.6B-onnx`); `tokenizer.json` alone is 11.4 MB | >1.2 GB | 61.82 MTEB-R; 1024d, Matryoshka, instruction-aware | Qwen license | no (dev ceiling only) |

Notes:

- MiniLM fp32 ONNX is 90 MB; its `tokenizer.json` is 711 KB (fits, but
  the weights don't).
- The 33M-param cluster (bge/gte/mxbai) all score ≈ the same on MTEB —
  there is no quality headroom to be had at the sizes that exist.
- MTEB is general-domain; our retrieval domain is narrow (709 ATT&CK
  patterns). The shared query set in `analysis/queries.jsonl` is the
  metric that actually matters here.

## What would fit

Budget 5.65 MB → at int8 (≈1 byte/param + overhead) a model must be
**≤ ~5M params**; at fp16 **≤ ~2.5M params**. No off-the-shelf text
embedder exists at that size with usable retrieval quality.

Vector storage is not the bottleneck: 709 docs × 384 dims = 1.09 MB fp32,
0.55 MB fp16, 0.27 MB int8. The model weights are the cost.

## The only in-zip path: custom distillation (option C)

- Target: 2–4 layer BERT, hidden 256–384, reduced vocab (~8–16k),
  contrastive/supervised training on query→technique pairs (KB cheat
  lines, the query set, LLM-generated paraphrases — see #94).
- Resulting artifact ≈ 1.5–3 MB int8 → fits with room to spare.
- Needs dev-time `torch` (dev machine only — never ACP, never the
  submission). Quality ceiling unknown; a 3M-param student is below
  MiniLM on general benchmarks, but the domain is narrow and the corpus
  is small, so it is not a priori hopeless.
- **Gate:** only worth it if the #93 ceiling measurement shows dense
  retrieval is substantially better than BM25(+expansion). If the ceiling
  itself is only marginally above the baseline, distillation buys nothing.

## Sources

- HF model cards + file sizes via HF API `content-length` on resolve URLs
  (2026-09-03): huggingface.co repositories `sentence-transformers/all-MiniLM-L6-v2`,
  `TrendHD/all-MiniLM-L6-v2-int8`, `BAAI/bge-small-en-v1.5`,
  `Alibaba-NLP/gte-small-en-v1.5`, `mixedbread-ai/mxbai-embed-small`,
  `nomic-ai/nomic-embed-text-v1.5`, `Qdrant/Qwen3-Embedding-0.6B-onnx`.
- MTEB numbers as reported on the respective model cards (not
  independently reproduced).
