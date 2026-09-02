# SIFS (SIFS Is Fast Search)

- **Category:** agent-tooling (code search)
- **Source:** [tristanmanchester/sifs](https://github.com/tristanmanchester/sifs) · MIT · Rust · crate [`sifs`](https://crates.io/crates/sifs) v0.4.0 (2026-05-28) · crates downloads at check: 166 (young project)
- **Code:** https://github.com/tristanmanchester/sifs · **Docs:** `docs/cli.md`, `docs/benchmark-report.md`, `docs/architecture.md` in-repo
- **Reviewed:** 2026-08-30 (built and measured locally, see [measurements](#measurements-2026-08-30-local))

## What it is

Local code-search engine for agents: ranked file paths, line ranges, and code
chunks. Three interfaces: CLI, Rust library, stdio MCP server. Three search
modes over a chunked index:

| mode | how | model needed |
| --- | --- | --- |
| `bm25` | sparse lexical (stemmed identifiers, definition boosts, noise penalties for tests/legacy/examples) | **none — fully offline** |
| `semantic` | embeddings via `minishlab/potion-code-16M` through a local Model2Vec loader (tensors load into the Rust process, CPU-only) | 61.4 MB (see below) |
| `hybrid` (default) | RRF fusion of both + rerank; query-aware weighting (symbol-like → BM25-heavy, NL → semantic-heavy) | 61.4 MB |

Primitives beyond `search`: `symbol <name>` (definitions vs references),
`outline <file>` (symbols + chunks per file), `find-related <file> <line>`,
`pack <query> --budget-tokens N` (token-budgeted context pack: primary chunks
+ file headers + symbol breadcrumbs), `list-files`, `status`, profiles,
`--json/--jsonl` output, `.gitignore`-aware file walking (same behavior as
ripgrep/fd), 25+ languages.

Embedding model facts (verified via HF API 2026-08-30):
`minishlab/potion-code-16M` — `model.safetensors` 64 299 272 B (~61.4 MB) +
`tokenizer.json` ~1 MB, **license: MIT** (`license:mit` tag). Same model
family Semble uses (MinishLab's model2vec).

## Published benchmarks (vendor-reported)

Across **63 pinned open-source repos, 19 languages, 1 251 annotated tasks**:

| method | NDCG@10 | cold index | warm query |
| --- | ---: | ---: | ---: |
| CodeRankEmbed Hybrid (neural) | 0.8617 | 57.3 s | 16.9 ms |
| Semble | 0.8544 | 439.4 ms | 1.3 ms |
| **SIFS** | **0.8471** | **167.0 ms** | **2.7 ms** |
| grepai | 0.5606 | 35.0 s | 47.7 ms |
| ripgrep | 0.1257 | — | 8.8 ms |

By query type (SIFS): symbol 0.9711 · semantic 0.8412 · architecture 0.7857.
Vendor numbers; methodology doc exists in-repo (`docs/benchmark-report.md`),
repos pinned, annotations on file — plausible, but not independently
reproduced by us. The ripgrep row (0.1257) is the relevant baseline delta.

## Measurements (2026-08-30, local)

Environment: host build (Debian, glibc), target container
`secureintelligent/acp:latest` (Debian 12). Artifacts in
`tmp/code-search-research/` (gitignored).

**Binary size** (x86_64-unknown-linux-gnu, `cargo install --locked sifs`):

| build | raw | zip (deflate-9) |
| --- | ---: | ---: |
| default release (dynamic, gnu) | 16 MB | not measured |
| `CARGO_PROFILE_RELEASE_LTO=true CODEGEN_UNITS=1 PANIC=abort STRIP=symbols` | **9.3 MB** | **3.87 MB** |

The optimized build runs in the ACP container (`sifs --version` via
`docker run -v`): glibc-compatible. Zip headroom: 3.87 MB + ~40 KB agent ≈
3.9 MB total vs the 10 MB gate.

**Behavior** (corpus: `tasks/contest-find-sqli-login/environment/app`, 621 lines):

- Warm query: 29 ms wall, `elapsed_ms: 4` (JSON); controlled re-measurement
  (same binary, same corpus, three consecutive runs): **5–6 ms wall each**.
  The original 6.2 s first-run outlier (0.18 s CPU) was a one-time
  first-execution effect of the default build — not reproduced with the
  optimized build; cause unknown (first-run probe/cache init). Treat as a
  non-issue for now; monitor in the container.
- `symbol login` → `routers/auth.py:14 def login` ✓.
- `outline routers/auth.py` → per-file symbol/chunk map ✓.
- NL ranking (BM25-only): query "find the sql injection vulnerability in the
  login flow" ranked `db.py` (seed SQL) **above** the vulnerable
  `routers/auth.py`; an identifier-flavored query ("where is the sql query
  built for login") ranked `routers/auth.py` first with the exact f-string
  chunk. → BM25 = strong on identifiers, weak on NL intent; hybrid is the fix
  but needs the 61.4 MB model (dev-only).
- Token cost on this small app (chars ÷ 4 estimate):
  - baseline `rg -n "SELECT id FROM users"` + full file read: **~218 tokens**
  - `sifs search` (top-3, NL q): ~862 tokens · (symbol-ish q): ~839 tokens
  - `sifs pack --budget-tokens 800 --json`: **~2 370 tokens** — the `pack`
    JSON envelope (breadcrumbs/symbols/why metadata) inflates ~2–3× over the
    stated token budget; a tool wrapper must strip it and re-emit compact text.
  - Conclusion: on ≤ ~1 k-line targets, plain grep+read is already cheaper
    than SIFS output; SIFS's edge = ranking quality, symbols, outlines,
    find-related, and large corpora where read-everything explodes.

## Fit for Shlepa

- **Contest-viable:** `bm25` mode + optimized binary in the zip (3.87 MB).
  No model, no network, no new runtime deps, MIT license.
- **Dev-only:** `hybrid`/`semantic` (cache model via `sifs model pull` in the
  dev image) — for measuring the NL-quality delta in A/B experiments.
- **Integration shape:** the agent already shells out (`bash` tool, subprocess
  pattern in `core.py`); a Python `code_search` tool wrapping `sifs ... --json`
  with compact re-formatting is a small module. MCP mode is not needed
  (pydantic-ai agent, no MCP client in the stack).
- **Risks:** young project (v0.4.0, 166 crate downloads, first release 2026);
  API churn possible — pin version, vendor the binary, keep the rg fallback.
  glibc coupling: rebuild per target glibc or test in the ACP image (done once
  for v0.4.0).

## Reproduction

```sh
cd tmp/code-search-research
# default build (16 MB)
cargo install --root install --locked sifs
# size-optimized build (9.3 MB raw / 3.87 MB zipped)
CARGO_PROFILE_RELEASE_LTO=true CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
CARGO_PROFILE_RELEASE_PANIC=abort CARGO_PROFILE_RELEASE_STRIP=symbols \
  cargo install --root install-opt --locked sifs
# container smoke
docker run --rm -v $(pwd)/install-opt/bin/sifs:/sifs:ro \
  --entrypoint /sifs secureintelligent/acp:latest --version
# BM25-offline search
install-opt/bin/sifs search "query" --source <path> --mode bm25 --offline --limit 5
```

## Sources

- README (benchmarks, modes, model): https://github.com/tristanmanchester/sifs (fetched 2026-08-30)
- crates.io: https://crates.io/crates/sifs (v0.4.0, 166 downloads)
- Model: https://huggingface.co/minishlab/potion-code-16M (safetensors 64 299 272 B)
- Benchmark methodology: `docs/benchmark-report.md` in-repo (not independently reproduced)
- Local measurements: `tmp/code-search-research/` (build logs, zip test, query timings)
