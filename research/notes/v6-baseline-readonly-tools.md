# Baseline Read-only Orientation Tools (v6-rewrite)

- **Category:** agent-architecture (tooling / phase gating)
- **Source:** user request 2026-09-06 ("do it in the loop like v6, not the
  old v3"), port from `origin/dev` (feature/forensics arm era), local
  search-bench 2026-08-31
- **Reviewed:** 2026-09-06
- **Related:** `readonly-plan-phase.md` (the plan-phase design that makes
  these tools load-bearing), `readonly-tools.md` (read-only tool patterns,
  on `origin/dev`), `recon-tool-conversion.md` (recon as a registered
  tool), `research/code_search/analysis/search_bench_20260831-1600.md`
  (engine ground truth)

## Motivation

On `origin/dev`, `code_search` / `file_outline` / `log_triage` existed but
were **dev-only, env-gated** (`AGENT_CODE_SEARCH` unset = off) and never
steered in a free-form main phase — usage across the v3 trace corpus was
negligible (code_search 2 calls / 98 runs; log_triage 1 / 49; file_outline
1 / 49). The search-bench already predicted the engine outcome (bm25
strictly beats the rg fixed-string scan), but the engine only ever got
measured un-steered.

The v6-rewrite loop (`feature/v6-readonly-baseline`) removes env-gating
entirely: tool availability is decided once per run by the `[tool_policy]`
phase x iteration matrix (single source, w6 decision). The user direction
for this branch: these orientation tools are **baseline** — in the read-only
PLAN phase and the WORK phase alike, no arm, no env switch. That is the
steering the plan phase is supposed to provide (see
`readonly-plan-phase.md`, "Prompt design").

## What was ported

| file | from `origin/dev` | change |
|---|---|---|
| `agent/shlepa_agent/code_search.py` | verbatim (byte-identical) | — |
| `agent/shlepa_agent/log_triage.py` | verbatim (byte-identical) | — |
| `agent/tests/test_code_search.py` | verbatim (byte-identical) | — |
| `agent/tests/test_log_triage.py` | near-verbatim | env-gate assertions dropped |
| `agent/tools/bin/{sifs, PROVENANCE.md, rebuild-sifs.sh}` | verbatim | — |
| `agent/shlepa_agent/tools/code_search.py` | rewritten | env-gate removed; plain Tool records (same shape as `search`) |
| `agent/shlepa_agent/tools/log_triage.py` | rewritten | same |
| `agent/shlepa_agent/config.{py,toml}` | new sections | `ToolsConfig` entries, `CodeSearchConfig` (engine), env overrides, `[tool_policy]` routing |
| `agent/shlepa_agent/prompts/{base,plan,work}.md` | new blocks | ORIENTATION TOOLS steering (see below) |
| `agent/tests/test_baseline_tools.py` | new | registry/policy/reserve/env/e2e pins |

### Engine behaviour (unchanged from dev)

- **code_search**: BM25-offline retrieval via the bundled SIFS binary
  (`tools/bin/sifs`, 0.4.0, MIT, x86_64 glibc; sha256 pinned, rebuild
  script in `tools/bin/`). Two engines: `sifs` (baseline) and `rg`
  (preinstalled ripgrep fixed-string, fallback). A missing/broken sifs
  binary degrades to rg/regex inside the engine — **never crash**.
  Compact text output (not the SIFS JSON envelope, which inflates 2–3×
  over the token budget): per-file grouped match windows with an
  enclosing-symbol annotation, strict token budget (default 1500),
  truncation marker. Results carry UNTRUSTED markers (environment data).
- **file_outline**: def/class/func symbols of one file with line ranges —
  same engine family, same never-crash contract.
- **log_triage**: pure-stdlib deterministic triage of log/evidence files —
  per-file record counts, time ranges, top entities, rare single-occurrence
  IOC candidates; ≤4KB output; signals, not verdicts (the LLM reasons).

### Wiring (the v6 delta)

- **Registry**: `ALL_TOOLS` gains `code_search`, `file_outline`,
  `log_triage` (always registered; availability comes from the matrix).
- **Config**: `[tools.code_search]`, `[tools.file_outline]`,
  `[tools.log_triage]` (all `enabled = true`, per-call wall 30s — the
  regime bash cap; log_triage 8KB max_output); `[code_search] engine =
  "sifs"`. Env overrides kept for dev A/B: `SHLEPA_CODE_SEARCH`,
  `SHLEPA_CODE_SEARCH_ENGINE`, `SHLEPA_LOG_TRIAGE`.
- **Policy matrix**: PLAN = `read, recon, search, code_search,
  file_outline, log_triage` (read-only, no bash/write/edit); WORK gains the
  same three on top of the full set. Finalization reserve (w3-2) blocks all
  three — they are exploratory, not salvage.
- **Prompts**: `base.md` "RECON TOOL" section → "ORIENTATION TOOLS" (one
  block for all six, read-only and cheap, use before bash probes);
  `plan.md` gets the "orient FIRST, one call per surface" guidance with a
  forensics example (recon → log_triage → read flagged lines); `work.md`
  gets the retrieval/triage one-liners. Descriptions stay the pydantic
  docstrings (shared across phases); steering lives in the prompt files.

## Benchmarks (local, our corpora, 2026-08-31)

| query style | rg hit@1 | sifs bm25 hit@1 |
|---|---|---|
| keyword | 0.25–1.00 | 0.67–1.00 |
| natural language | 0.00 everywhere | 0.50–1.00 |

sifs call cost: 4–7 ms on small corpora; ~1.8 s per call on a 10k-file
corpus (index rebuild per call) — inside the 30 s per-call wall with large
margin. Full matrix:
`research/code_search/analysis/search_bench_20260831-1600.md`.

## Zip consequence (danger zone: ≤10 MB)

The SIFS binary is 9.3 MB raw (9,711,816 bytes), ~3.87 MB deflate-9 in the
submission zip. Current zips are ~150 KB without it; with it the submission
is ~4–5 MB — well under the 10 MB cap (the earlier 9.5 MB estimate in
`readonly-plan-phase.md` assumed the binary near-raw; deflate shrinks it
~2.4×). Verify with `shlepa zip` before each submission (the zip step
enforces the gate).

## Tests

352 passed, 0 skipped (sifs present and runnable on this host):

- engine-level: ported `test_code_search.py` (447 lines: both engines,
  outline, token budget, never-crash paths) + `test_log_triage.py`
  (JSONL/text triage, caps, error shapes);
- `test_baseline_tools.py`: registry + shipped config (all enabled, engine
  sifs), plan matrix stays read-only, work has the full set, finalization
  reserve blocks them, env overrides, one real end-to-end call per tool on
  a tiny fixture (the sifs e2e uses the engine's `SIFS_BUNDLED` constant and
  skips only when the binary is missing **or non-executable**);
- existing pins updated: `test_config`, `test_phases`, `test_tool_policy`,
  `test_tools` now assert the six-tool plan / nine-tool work sets.

## Open

- **A/B** (from `readonly-plan-phase.md`): baseline-with-tools vs
  baseline-without on the SOC/forensics + seccodebench presets, N≥2 per
  task; read digests on whether plan findings were reused by the work phase.
- The +smart-grep/+sifs/+forensics arms retire once the baseline absorbs
  the tools (their only reason to exist was steering the un-steered main
  phase).
- SIFS semantic/hybrid modes need the 61.4 MB embedding model — dev-only
  forever (`research/code_search/notes/sifs.md` on `origin/dev`).

## Sources

- Local: `agent/shlepa_agent/{code_search,log_triage}.py` (verbatim from
  `origin/dev`), `agent/tools/bin/PROVENANCE.md`,
  `research/code_search/analysis/search_bench_20260831-1600.md`, v3 trace
  usage counts from `readonly-plan-phase.md`.
- `origin/dev` refs: `agent/shlepa_agent/tools/{code_search,log_triage}.py`
  (the env-gated versions replaced here), `research/notes/readonly-tools.md`.
