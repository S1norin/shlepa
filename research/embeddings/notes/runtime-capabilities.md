# Runtime capabilities: ACP image + LLM endpoints

Reviewed: 2026-09-03

## ACP image `secureintelligent/acp:latest` (docker-verified)

`/app/.venv` is Python 3.12.13 with 242 packages. Packages relevant to
embeddings (checked with `importlib.metadata`):

| package | version | implication |
|---|---|---|
| `onnxruntime` | 1.27.0 | CPU ONNX inference out of the box — the key fact |
| `tokenizers` | 0.23.1 | HuggingFace fast tokenizer; loads `tokenizer.json` offline, no `transformers` needed |
| `numpy` | 2.5.0 | vector math (cosine, matmul) |
| `chromadb` | 1.1.1 | in-memory vector store available (probably overkill for 709 vectors) |
| `llama-index` | 0.14.23 | RAG framework present (part of the ACP harness); not needed for our KB |
| `openai` | 2.44.0 | client usable for `/v1/embeddings` if the endpoint offers it |
| `tiktoken` | 0.13.0 | token counting |
| `torch`, `transformers`, `sentence-transformers`, `scikit-learn` | — | **absent**; pure-Python transformer inference is out of the question |

Re-runnable verification (from a host with docker + the image pulled):

```bash
docker run --rm -v check.py:/tmp/c.py --entrypoint /app/.venv/bin/python \
    secureintelligent/acp:latest /tmp/c.py
```

**Implication.** ONNX inference = `onnxruntime` + `tokenizers` + `numpy`,
all preinstalled. The earlier rejection rationale in
`research/notes/mitre-rag-decision.md` ("no torch → pure Python too slow")
is void: a quantized ONNX model runs with **zero new dependencies**.

## Dev endpoint (this machine)

- `POST /v1/embeddings` → **501** "does not support embeddings. Start it
  with `--embeddings`" — the llama.cpp server rejects by default.
- llama.cpp supports `--embeddings`, `--pooling {none,mean,cls,last,rank}`,
  an OpenAI-compatible `/v1/embeddings`, and a `/reranking` endpoint.
- Enabling requires a user action (restart llama.cpp) — tracked in #93.

## Contest endpoint

- Contract is chat completions only; embeddings are **undocumented**.
- The contest model is unknown → doc vectors cannot be precomputed for it
  (query side must embed with the same model). See
  `notes/endpoint-embeddings.md` for why that kills the startup-embedding
  design.

## Sources

- Docker image inspection, 2026-09-03 (`/app/.venv/bin/python`,
  `importlib.metadata`).
- Curl probe of `localhost:11434/v1/embeddings`, 2026-09-03 (501).
- llama.cpp server flags: https://github.com/ggml-org/llama.cpp (README,
  `--embeddings`/`--pooling`).
