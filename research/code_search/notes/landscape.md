# Code-search tool landscape (other candidates)

One-paragraph digests for every tool in the candidate list, with verification
status. Statuses: **verified** (primary source fetched 2026-08-30) ·
**partial** (existence verified, some claims unverified) · **unverified**
(existence or claims not confirmable from primary sources).

Cross-tool decision table: [`../analysis/fit-matrix.md`](../analysis/fit-matrix.md).

## ast-grep — **verified, strong backup candidate**

[ast-grep/ast-grep](https://github.com/ast-grep/ast-grep) — 15 693★, Rust,
**MIT**, v0.45.2 (2026). "CLI tool for code structural search, lint and
rewriting": tree-sitter pattern matching with metavariables
(`$FUNC($ARG)`), multi-language, single static binary, fully offline, no
model. Latest release Linux asset: `app-x86_64-unknown-linux-gnu.zip` =
7.75 MB (zip-compressed size of the binary not measured). Role for us:
structural queries ("all calls of `subprocess.*`", "string-built SQL") —
complements lexical search, different strength from SIFS BM25. If SIFS
integration hits a snag, ast-grep is the fallback to bundle.

## jCodeMunch — **verified, license caution**

[jgravelle/jcodemunch-mcp](https://github.com/jgravelle/jcodemunch-mcp)
— 2 632★, Python, PyPI. Tree-sitter AST index; retrieves exact functions/
classes/constants with byte offsets, outlines, `get_blast_radius`. Claims
86–99% token savings (27.4× fewer tokens than a grep-and-read agent; vendor
benchmark, tiktoken cl100k_base, 3 repos). **Dual-use license**: free for
personal/academic/non-commercial; commercial paid. Bundling it in a contest
submission sits uncomfortably close to that line — avoid bundling; useful as a
design reference (symbol index + blast radius) we can copy into our own
wrapper.

## cocoindex-code — **partial**

[cocoindex-io/cocoindex-code](https://github.com/cocoindex-io/cocoindex-code)
— 2 682★, Python, Apache-2.0. "AST-based semantic code search" on the
Rust-based CocoIndex engine; CLI + MCP + skill install; claims "instant token
saving by 70%". Whether "semantic" needs an embedding model (and which) was
not confirmed from the fetched README sections. Apache-2.0 is bundling-safe;
needs a dedicated pass before it becomes a candidate.

## ChunkHound — **verified, out of fit for contest**

[chunkhound/chunkhound](https://github.com/chunkhound/chunkhound) — 1 422★,
Python (`uv tool install`). DuckDB-backed index, tree-sitter parsing,
`research` mode with citations. **Regex search works with no provider;
semantic search requires an embedding provider** (VoyageAI/OpenAI/Ollama);
deep research also needs an LLM provider. Offline contest fit = regex mode
only, which duplicates what `rg` already gives us. The cAST-algorithm claim is
unverified in the README (see [semble.md](semble.md#cast-paper-the-chunking-research)).

## codeix — **verified, too young**

[montanetech/codeix](https://github.com/montanetech/codeix) — 9★, **Rust**
(not TypeScript as the source chat said). MCP-first "pre-built map":
symbols with kinds/signatures/parents/line ranges, references, callers, prose
scope (comments/docstrings/strings). Portable `.codeindex/` JSONL format
committed to git; tree-sitter + SQLite FTS5. 9 stars, single maintainer, no
benchmark data → watch, don't build on. Its known limitation (symbol-level
search, weak on implementation-text queries) is inherent to the design.

## zoekt / zoekt-mcp — **verified, heavy**

Sourcegraph's [Zoekt](https://github.com/sourcegraph/zoekt): mature single-Go-binary
indexed code search (regex + symbol-aware), fully offline. No recent GitHub
release assets found (release pipeline effectively quiet) — version drift risk.
Wrappers ([najva-ai/zoekt-mcp](https://github.com/najva-ai/zoekt-mcp) 22★,
others) are small projects. Binary + separate index files add operational
weight (re-index per task) with no capability SIFS BM25 lacks for our
small/medium task corpora. Not a candidate; listed for completeness.

## Frigg — **partial, too young**

[bnomei/frigg](https://github.com/bnomei/frigg) — 5★, C. "Fast local code
intelligence for AI agents powered by AST Treesitter, SCIP, semantic search"
(lexical/hybrid/symbol). By a known devtools author but 5 stars and no
benchmark data. Not a candidate yet.

## CodeVault — **partial, too young, wrong runtime**

[shariqriazz/codevault](https://github.com/shariqriazz/codevault) — 0★,
**TypeScript**. "Semantic code indexing and search with CLI and MCP, hybrid
retrieval". No node runtime in the ACP image → not contest-viable anyway; 0
stars → not a candidate.

## semcode — **unverified (minor project exists)**

[GoodbyePlanet/semcode](https://github.com/GoodbyePlanet/semcode) — 7★, MCP
server, "indexes code symbols and commit history, combines dense emb[eddings]
+ …". The source chat's specifics (TypeScript CLI, 1.5 MB, 82% token saving,
16× slower than grep, grep-routing) were not confirmable from any primary
source found. (`facebookexperimental/semcode` 161★ is an unrelated project.)
Not a candidate.

## jcode — **unverified, likely a different kind of tool**

No primary source matches the description (Python feature graph in SQLite,
`jcode_blast_radius`, 27.8 MB base / 167 MB with embeddings, OS-level
sandboxing). GitHub only shows forks of a "**Coding Agent Harness**" named
jcode (e.g. `chapzin/jcode-harness`) — i.e. a coding-agent CLI, not a search
library; the "blast radius" and feature-graph details resemble jCodeMunch
capabilities. Treat the entire jcode entry from the source chat as
unverified; do not plan on it.

## hound-mcp — **unverified**

No repository found matching a Hound (regex text search) + tree-sitter MCP
wrapper. Likely another hallucinated/renamed entry.

## Tools we added to the search (not in the source chat)

- **ripgrep** — already in the ACP image (`/usr/bin/rg`, verified). The
  zero-dependency baseline and the engine behind the `smart-grep` arm.
- **Aider repomap** — [aider/repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py)
  (verified to exist): tree-sitter symbol extraction + BM25 ranking of
  symbols/files against the conversation to keep a compact "map" of relevant
  code in context. The canonical design pattern for "give the agent a map, not
  the files" — worth stealing regardless of which search engine we bundle.
- **CodeRankEmbed** — the neural baseline in the SIFS/Semble benchmark
  (NDCG 0.8617, 57.3 s cold index): too slow and too big for offline agent
  use; listed to anchor "how close BM25 comes to a dedicated transformer".

## Verification notes

The source chat's size table (Codeix 271 KiB, semcode 1.5 MB, jcode 27.8 MB,
SIFS 1.16 MiB) is not trustworthy as stated: e.g. SIFS's 1.16 MiB matches
neither the 16 MB default nor the 9.3 MB optimized **binary** we built; it
appears to be a source/crate figure. We measured what matters for the zip
gate (compressed archive bytes) directly — see the fit matrix.
