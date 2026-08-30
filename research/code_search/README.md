# Code search for the agent

Research on token-efficient code search for Shlepa: what to give the agent
instead of raw `grep` + full-file `read_file` when it has to find, read, or
understand code in a task environment.

Conventions: [`../README.md`](../README.md). This directory is self-contained
(one idea per note, cross-cutting analysis in `analysis/`).

## Problem statement

The agent's current context cost for code-centric tasks (vuln-analysis,
codefix, CTF rev) comes from two tool behaviors:

- `read_file` returns the **whole file** truncated to 16 000 chars
  (`agent/shlepa_agent/core.py`, `max_tool_output`). On a 400-line file the
  agent pays ~1 000–1 500 tokens to see a 20-line function.
- The only search path today is `bash` + `rg`/`grep` (ripgrep **is**
  preinstalled in the ACP image), which returns raw `file:line:text` lines —
  the agent then re-reads full files to get context, repeatedly.

Token budget is 300k (`AGENT_TOKEN_BUDGET` in `core.py`); a medium task
spends a large share just locating and re-reading the same code. A compact,
ranked, chunk-level search primitive is the fix. This is the same ACI insight
as `research/notes/toolsets-modular.md` (SWE-agent: tool design is a primary
success determinant).

## Hard constraints (verified 2026-08-30)

| constraint | value | source |
| --- | --- | --- |
| Submission zip | **≤ 10 MB compressed** (`MAX_ZIP_BYTES`, `cli/shlepa_cli/zip_build.py:17`, checks `st_size` of the archive) | `shlepa zip` |
| Agent runtime | ACP image `secureintelligent/acp:latest`: Debian 12, Python 3.12 in `/app/.venv`, **ripgrep preinstalled** (`/usr/bin/rg`), git, jq, **no node**, **no tree-sitter**, **no internet** | `docker run` inspection of the local image |
| Zip content today | 6 files, ~39 KB uncompressed (`run.sh`, `agent.py`, `shlepa_agent/*`, `tools/recon.py`) | `dist/` |
| Telemetry rule | No OTel deps in agent base env; `telemetry/` excluded from zip | `agent/pyproject.toml`, AGENTS.md |
| `agent/agent.py` | must stay byte-identical to upstream | AGENTS.md |
| Dev vs submission split | Dev images are built `FROM` the task env image with the agent baked in (`cli/shlepa_cli/dev_env.py`); dev-only extras (models, tools) never ship in the zip | `dev_env.py` docstring |
| Binary bundling precedent | Issue #46 ("Bundle ffuf binary", deferred) is the first "bundle a binary in the zip" ask | GitHub issues |

A tool is **contest-viable** only if it runs offline inside the ACP image with
everything (code + model + grammar) inside the zip. Dev-only is fine for A/B
arms, but the winning arm must pass the zip gate.

## Master index

| doc | what it is |
| --- | --- |
| [notes/sifs.md](notes/sifs.md) | SIFS digest — primary candidate; verified, locally built and measured (BM25-offline mode) |
| [notes/semble.md](notes/semble.md) | Semble digest — same embedding family as SIFS; model too big for the zip; cAST paper verified |
| [notes/landscape.md](notes/landscape.md) | One-paragraph digests of every other candidate (jcodemunch, cocoindex-code, ChunkHound, ast-grep, codeix, zoekt, frigg, codevault, semcode, jcode, …) with verification status |
| [analysis/fit-matrix.md](analysis/fit-matrix.md) | Cross-cutting: candidates × Shlepa constraints, measured numbers, tool-interface sketch, recommended arms, A/B design |

## Key findings (2026-08-30)

1. **SIFS** (`tristanmanchester/sifs`, Rust, MIT, v0.4.0) is the strongest
   fit: `bm25` mode is fully offline with **no model files**; the binary builds
   to 9.3 MB with an LTO/strip profile and **3.87 MB compressed in the zip**
   (agent code is ~40 KB, so the zip lands at ~3.9 MB — well under 10 MB).
   Runs in the ACP container. `hybrid`/`semantic` modes need the 61.4 MB
   `minishlab/potion-code-16M` model → **dev-only** (cache in the dev image).
2. **Semble** (5.9k★) and SIFS share the embedding model; Semble is
   Python+model2vec, ~61 MB model → dev-only. Its published NDCG@10 (0.854)
   vs SIFS (0.847) over 63 repos / 1 251 tasks is a fair comparison; ripgrep
   scores 0.1257 on the same benchmark.
3. **The "csp Rust port of Semble" does not exist**: crates.io `csp` is a
   Content-Security-Policy helper. `csp` claims marked unverified/incorrect.
4. BM25-only is strong on **identifier** queries, weaker on natural-language
   intent queries (measured on `contest-find-sqli-login`: NL query ranked
   `db.py` over the vulnerable `routers/auth.py`). Hybrid (dev-only) is the
   quality fix; BM25 + agent-side query phrasing is the offline mitigation.
5. On **small** targets (≤ ~1 k lines) plain `rg` + targeted reads is already
   cheap (~200 tokens measured); the search tool's value scales with corpus
   size (CyberGym libmagic, future CVE-Bench WordPress) and with the
   symbol/outline/find-related primitives it adds regardless of size.
6. Tooling that needs **node** (codeix, codevault, semcode) is out — no node in
   the ACP image. Tools needing an **external embedding provider** (ChunkHound
   semantic) are out for contest use. **jCodeMunch**'s dual-use (non-commercial
   free) license is a bundling risk.

## Decision record (current)

- **Build two contest-viable arms and A/B them against baseline** (uses the
  toolset registry of issues #51–#53; precedent #46 for binary bundling):
  - arm `smart-grep`: pure-Python compact wrapper over preinstalled `rg`
    (match windows, per-file grouping, token budget) — zero new dependencies;
  - arm `sifs`: SIFS binary in the zip, BM25-offline mode (`search`,
    `symbol`, `outline`, `find-related`, `pack` with token budget).
- **Dev-only experiment** to size the quality delta: SIFS `hybrid` vs
  `bm25` on NL queries (model cached in the dev image, never in the zip).
- Default agent behavior stays byte-identical until an arm wins the A/B
  (regression gate: `shlepa smoke` + unchanged default prompt/tool list).

## Tracking (GitHub issues, 2026-08-30)

Plan: `code-search-tools` (plan_tasks). Issues:

| issue | ask |
| --- | --- |
| #54 | Prototype `code_search` tool (smart-grep + SIFS BM25) behind env var |
| #55 | Vendor size-optimized SIFS v0.4.0 binary with provenance |
| #56 | Measure search engines: tokens-to-locate + hit rate on task corpora |
| #57 | Dev-only SIFS hybrid arm: model pull at dev image build + zip guard |
| #58 | A/B: baseline vs +smart-grep vs +sifs on code-centric families |
| #59 | Ship SIFS BM25 binary in submission zip + offline ACP smoke |

## Open questions

- Does hybrid's NL quality lift convert into solved-rate on our task families?
- Zip-compressed size of ast-grep (7.75 MB Linux asset) — backup candidate if
  SIFS integration hits a snag (structural patterns, MIT, 15.7k★).
- SIFS first-execution outlier (6.2 s once, 0.18 s CPU, default build): not
  reproduced on the optimized build (5–6 ms wall per run, controlled
  re-measurement) — monitor in the container, do not block on it.

## Sources

- Tool sources and measurements: see the `Sources` sections of each note.
- Local measurements: `tmp/code-search-research/` (gitignored; SIFS builds,
  logs, zip test). Rebuild recipe in [notes/sifs.md](notes/sifs.md#reproduction).
