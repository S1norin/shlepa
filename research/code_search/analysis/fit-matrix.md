# Fit matrix: code search candidates × Shlepa constraints

Cross-cutting analysis (2026-08-30). Inputs: the notes in `../notes/`, the
hard-constraint table in [`../README.md`](../README.md), and local
measurements from `tmp/code-search-research/`.

## Constraint recap

1. Submission zip ≤ **10 MB compressed** (`zip_build.py` checks `st_size`).
2. Contest runtime: ACP image — Debian 12, **rg preinstalled**, no node,
   python 3.12 in `/app/.venv`, **offline**, task code in `/app`.
3. Agent base env: only `pydantic-ai-slim[openai]` + `python-dotenv`
   (no new core deps without a strong reason; telemetry stays out).
4. `agent.py` byte-identical; telemetry/ stripped from zip.
5. Dev split: anything not in the zip can live in dev images only.
6. License: bundling means redistribution — prefer permissive (MIT/Apache);
   dual-use/proprietary needs a decision.

## Candidate matrix

| candidate | offline mode | model needed | zip-compressed size (measured/est.) | license | maturity | verdict |
| --- | --- | --- | --- | --- | --- | --- |
| **SIFS `bm25`** | yes (no model) | none | **3.87 MB measured** (9.3 MB binary, LTO/strip) | MIT | v0.4.0, young (166 crate dl) | **SHIP ARM** — bundle in zip |
| SIFS `hybrid` | yes, after `model pull` | 61.4 MB potion-code-16M (MIT) | n/a (dev image only) | MIT | same | **DEV-ONLY ARM** — A/B quality reference |
| smart-grep (own, over `rg`) | yes | none | ~20–40 KB (python module) | ours | — | **SHIP ARM** — zero-dep baseline |
| Semble | no (needs model) | 61.4 MB | n/a | MIT | 5.9k★, active | dev-only reference; no integration |
| ast-grep | yes | none | ~7.75 MB asset, zip size unmeasured (est. 2.5–4 MB) | MIT | 15.7k★, active | **backup** if SIFS integration fails; structural patterns as a future 3rd arm |
| jCodeMunch | yes | none | PyPI wheel + tree-sitter native libs (unmeasured, likely 5–10 MB) | **dual-use** | 2.6k★ | no bundling (license); design reference |
| cocoindex-code | unclear ("semantic") | unverified | unmeasured | Apache-2.0 | 2.7k★ | needs dedicated pass; not v1 |
| ChunkHound | regex only | external provider for semantic | ~4 MB est. | unverified | 1.4k★ | out (regex = redundant with rg) |
| codeix / codevault / semcode / frigg | — | — | — | — | ≤9★ | out (too young; TS ones need node) |
| jcode / hound-mcp / "csp" | — | — | — | — | unverified | out (not real as described) |
| zoekt(-mcp) | yes | none | Go binary (est. 15–30 MB) | Apache-2.0 | mature, quiet releases | out (heavy, no unique capability) |
| CodeRankEmbed | no (neural, 57 s cold index) | large | n/a | — | research | out |

## Measured numbers (2026-08-30)

- SIFS binary: default release 16 MB → optimized (LTO, codegen-units=1,
  panic=abort, strip) **9.3 MB raw / 3.87 MB zipped (deflate-9)**.
- Runs in `secureintelligent/acp:latest` (glibc OK, `sifs 0.4.0`).
- Warm query 29 ms wall / 4 ms reported; controlled re-measurement 5–6 ms
  wall per run; the one-off 6.2 s first-execution outlier (default build)
  did not reproduce — monitor, don't block.
- Corpus `contest-find-sqli-login` app (621 lines): grep+read ≈ 218 tokens vs
  `sifs search` ≈ 840–860 tokens vs `sifs pack --budget-tokens 800 --json` ≈
  2 370 tokens (JSON envelope inflates 2–3× the stated budget → wrapper must
  strip metadata and re-emit compact text).
- BM25 NL weakness: "find the sql injection vulnerability in the login flow"
  ranked `db.py` over vulnerable `routers/auth.py`; identifier-flavored query
  ranked `routers/auth.py` first. (Mitigations: prompt the agent to prefer
  identifier/keyword phrasing; hybrid mode in dev arms.)

## Recommended tool interface (design sketch)

New agent tool(s), added via the toolset registry (issues #51–#53) so each
search flavor is an A/B arm, not a permanent change:

```
code_search(query, path=".", mode="auto", limit=5, context_lines=3, max_tokens=1500)
  → compact ranked results:
     1. routers/auth.py:14-27  (def login)
        <code window around the match, indented>
     2. db.py:11-19  (def get_pool)
        <window>
  engine: SIFS bm25 if the bundled binary is present, else rg --json fallback
  (never crash — the agent philosophy in core.py); on rg fallback: pattern
  mode only (no NL ranking), same output shape.
file_outline(path)
  → symbol map with line ranges (SIFS outline; fallback: regex defs/funcs)
```

Prompt guidance (SYSTEM_PROMPT "TOOLS" line + short section): "Use
`code_search` to locate code; read exact ranges via `read_file`/bash only for
the windows you actually need. Prefer identifier/keyword queries."

Arms to A/B (N≥2–3 repeats each, per the methodology in
`research/notes/toolsets-modular.md`):

| arm | content |
| --- | --- |
| `baseline` | today's 5 tools, unchanged prompt |
| `+smart-grep` | baseline + `code_search`/`file_outline` on the rg fallback engine |
| `+sifs` | baseline + same tools on the bundled SIFS BM25 binary |
| `+sifs-hybrid` (dev-only) | SIFS with cached potion-code-16M model (measures the NL-quality ceiling) |

Metrics (existing MLflow run schema): `solved`, `tokens_in/out/total`,
`tool_calls`, `duration_sec` + per-arm `toolset` tag; trace digests for
qualitative review. Task families with the most code to find:
seccodebench (fix), cybergym (large C corpus), contest find/fix-sqli,
ctf rev/web.

## Sequencing

1. Prototype both engines dev-only (no zip changes): dev image builds the
   SIFS binary + optional model pull; `code_search` module with engine switch
   behind env var (works before #51 lands).
2. Measurement harness: fixed query sets per task family → tokens-to-locate
   and ranking hits (script + results under this directory).
3. Wire the winning engine as a toolset arm (#51/#52) → A/B (#53 workflow).
4. Ship: bundle the SIFS binary in the zip (size gate in `shlepa zip`),
   container smoke (`shlepa smoke` + `submit-test`), keep rg fallback in the
   module so a missing/stale binary degrades instead of breaking.

## Open questions

- Controlled re-measurement of SIFS cold-index in the container (first-run
  6.2 s outlier vs 167 ms claim).
- Hybrid vs BM25 quality delta on our NL queries (dev experiment) — decides
  whether to invest in a small-model semantic path at all (e.g. a ≤9 MB
  embedding model in the zip would be a separate research spike; potion-code-16M
  is 61.4 MB and does not fit).
- ast-grep zip-compressed size (measure once, cheap) to keep the backup option
  quantified.
