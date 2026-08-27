# EvalBench

- **Category:** infra (generic offline eval harness)
- **Source:** github.com/cognis-digital/evalbench (COCL 1.0, PyPI
  `cognis-evalbench`; part of the "Cognis" agent/LLMOps tool family)
- **Code:** https://github.com/cognis-digital/evalbench
- **Reviewed:** 2026-08-27

## What it tests
**Not a benchmark** — an offline LLM/agent **evaluation harness with
regression gates**: `evalbench run suite.json --save run.json` then
`evalbench gate baseline.json run.json` — evaluate, then **gate CI** so
regressions fail the build. Self-hostable, MCP-native, CI-ready,
polyglot. Security-agnostic (general agent evaluation).

## Environment
Offline by design; local model endpoints or API; suite files define cases.

## Tasks
User-defined eval suites (JSON); harness handles execution, storage,
baseline comparison.

## Scoring
Suite-defined metrics + baseline-gate comparison (regression detection).

## Fit for Shlepa
- **Overlap:** process, not content. The pattern — *suite + run + baseline
  gate in CI* — is exactly what our dev loop could adopt (our MLflow runs
  already log per-task metrics; a gate step would catch agent regressions
  before submission).
- **Offline feasibility:** excellent.
- **Adaptation cost:** low to trial.
- **Recommendation:** optional tooling idea — prototype a baseline-gate
  over our `shlepa run` metrics (probably simpler to build a small gate
  script in `cli/` than to adopt the tool). Low priority. Provenance
  caveat: small vendor-adjacent project, no paper.

## Sources
- Repo: https://github.com/cognis-digital/evalbench
