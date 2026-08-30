# Semble

- **Category:** agent-tooling (code search)
- **Source:** [MinishLab/semble](https://github.com/MinishLab/semble) · MIT · Python · [`semble`](https://pypi.org/project/semble/) v0.5.5 (2026) · 5 968★ (2026-08-30), active
- **Code:** https://github.com/MinishLab/semble · **Related:** [model2vec](https://github.com/MinishLab/model2vec) (2 187★, the embedding engine), [model2vec-rs](https://github.com/MinishLab/model2vec-rs) (Rust impl)
- **Reviewed:** 2026-08-30

## What it is

"Fast and Accurate Code Search for Agents. Uses ~99% fewer tokens than
grep+read" (PyPI). Tree-sitter chunking (`semble-grammars` = prebuilt
tree-sitter grammars wheel), static embeddings via model2vec,
CPU-only, no API keys. Interfaces: Python library, CLI (`semble search ...`),
stdio MCP server, sub-agent install, AGENTS.md instructions. Indexes cached
and invalidated on file change; local path or git URL.

## Verified facts

- Dependencies (PyPI): `model2vec>=0.4.0`, `vicinity>=0.4.4`, `numpy`,
  `pathspec`, `orjson`, `semble-grammars` (tree-sitter native libs per
  language), optional `mcp` extra.
- Embedding model: `minishlab/potion-code-16M` — **model.safetensors
  64 299 272 B (~61.4 MB)** + tokenizer ~1 MB (HF API, 2026-08-30).
- Published: NDCG@10 **0.854** on the 63-repo / 1 251-task benchmark shared
  with SIFS (SIFS README table: Semble 0.8544 vs SIFS 0.8471 vs CodeRankEmbed
  Hybrid 0.8617 vs ripgrep 0.1257). Claims ~220× faster indexing and ~17×
  faster querying than the CodeRankEmbed neural baseline.

## cAST paper (the chunking research)

Verified via arXiv API: **"cAST: Enhancing Code Retrieval-Augmented Generation
with Structural Chunking via Abstract Syntax Tree"**
([arXiv 2506.15655](https://arxiv.org/abs/2506.15655), 2025-06-18):
AST-node-aware chunking (recursively split large nodes, merge siblings under
size limits); **+4.3 Recall@5 on RepoEval retrieval, +2.67 Pass@1 on
SWE-bench generation** vs line-based chunking. The claim that cAST is EMNLP
2025 and that ChunkHound implements it is **unverified** (not in arXiv
metadata; not stated in ChunkHound's README as fetched). The structural
chunking idea itself (what both Semble and SIFS do with tree-sitter) is well
supported by this paper.

## Fit for Shlepa

- **Zip:** no. Core Python deps + tree-sitter grammars + 61.4 MB model far
  exceed 10 MB, and the ACP image has no internet to fetch the model.
- **Dev-only:** yes — same role as SIFS hybrid: an A/B arm quality reference.
  But it adds nothing over SIFS hybrid that we measured: same model family,
  NDCG within 0.007 (0.8544 vs 0.8471), slower cold index (439 ms vs 167 ms),
  Python process + dependency wheel vs a single Rust binary. **SIFS covers the
  same capability surface with a smaller, offline-capable footprint.**
- Use it as the *quality reference point* in the benchmark harness, not as a
  tool to integrate.

## The "csp Rust port" claim

**Unverified / likely incorrect.** crates.io `csp` v3.0.0 is "a small Content
Security Policy creation helper" — not code search. The Rust side of the
MinishLab ecosystem is `model2vec-rs` (the embedding library SIFS uses), and
community Rust ports exist (`johunsang/semble_rs` 215★, `ooboai/sonar`, etc.)
but none is named `csp` in any primary source found. Treat "csp" as a
hallucinated detail in the source chat.

## Sources

- PyPI: https://pypi.org/project/semble/ (v0.5.5, deps, description — fetched 2026-08-30)
- GitHub: https://github.com/MinishLab/semble (README: NDCG 0.854, 99% token claim, MCP/CLI/sub-agent)
- Model size: https://huggingface.co/api/models/minishlab/potion-code-16M (file listing with sizes)
- cAST paper: https://arxiv.org/abs/2506.15655 (title, abstract, dates via arXiv API)
- csp check: https://crates.io/api/v1/crates/csp (description)
