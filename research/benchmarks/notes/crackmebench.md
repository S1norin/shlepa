# CrackMeBench

- **Category:** reverse-engineering (CrackMe-style binary validation)
- **Source:** arXiv 2605.10597, 2026
- **Paper:** https://arxiv.org/abs/2605.10597 (PDF: `papers/crackmebench.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Educational **CrackMe-style reverse engineering**: given only an
executable, recover the validation logic and produce an accepted input,
serial, artifact, or key generator. Focus: deterministic binary validation
problems with **executable oracles**, symbol-poor binaries, explicit local
tool access, externally scored submissions (no free-form explanations).

## Environment
**No-network Linux Docker sandbox**, standard reverse-engineering tools
(gdb, objdump, nm, strings, ...), equal shell interface for all agents.
Budget: **5 minutes, 3 scored submissions per task** — matches our
hard-timeout + finite-attempts reality.

## Tasks
v0 = **8 public calibration CrackMes + 12 generated main-score tasks**
built from seeded C, Rust, and Go templates (reproducible). The harder
generated half separates models sharply.

## Scoring
Executable oracle runs the binary against the submission; pass@3.
Published 3-model eval (5-min budget): GPT-5.5 11/12 (92%), Claude Opus
4.7 7/12 (58%), Kimi K2 5/12 (42%) on the generated split.

## Fit for Shlepa
- **Overlap:** RE is not a current contest family, but the *agent loop*
  (shell + standard tools + tight budget) is the closest existing benchmark
  to how Shlepa actually operates.
- **Offline feasibility:** **excellent** — designed for no-network Docker,
  i.e. literally our submission environment.
- **Adaptation cost:** **lowest of anything researched** — one CrackMe ≈ one
  Harbor task: `environment/` = binary + tools, `instruction.md` = "find the
  correct input", `tests/test.sh` = run oracle binary on the agent's
  submitted file.
- **Recommendation:** **adapt 3–4 tasks first** (`bench-crackme-*`); gives
  us a fast, deterministic, offline probe of tool-use quality with zero
  infrastructure work.

## Sources
- Paper: https://arxiv.org/abs/2605.10597
