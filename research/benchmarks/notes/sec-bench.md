# SEC-bench (+ SEC-bench Pro)

- **Category:** vuln-exploit (authentic security engineering: PoC + patching)
- **Source:** arXiv 2506.11791 (NeurIPS 2025); follow-up SEC-bench Pro
  arXiv 2605.26548
- **Paper:** https://arxiv.org/abs/2506.11791 (PDF: `papers/sec-bench.pdf`)
  · https://arxiv.org/abs/2605.26548 (PDF: `papers/sec-bench-pro.pdf`)
- **Code:** https://github.com/SEC-bench/SEC-bench
- **Reviewed:** 2026-08-27

## What it tests
**Authentic security engineering tasks** for LLM agents, fully automated:
a multi-agent scaffold automatically (1) constructs code repositories with
test harnesses, (2) **reproduces vulnerabilities in isolated environments**,
(3) generates **gold patches** — at $0.87/instance. Two tasks:
**PoC generation** and **vulnerability patching**. SOTA code agents reached
**at most 18% success** (base SEC-bench).

**SEC-bench Pro** (2026): long-horizon *vulnerability hunting* — 344
validated vulnerabilities across **V8, SpiderMonkey, and the Linux kernel**
(memory-safety, sandbox, JIT, race-condition, kernel-subsystem bugs); agent
reproduces a working PoC from the disclosed report. Strongest result:
Codex + GPT-5.5 at 58% overall. Also shows rule-based PoC judges are
insufficient → proposes an LLM-based judge for precise PoC grading.

## Environment
Isolated, reproducible per-vulnerability environments (containers);
auto-generated repos + harnesses; no internet needed by the agent beyond
what the environment provides.

## Tasks
- Base: PoC generation; vulnerability patching (gold-patch comparison +
  test harness).
- Pro: PoC reproduction from report for 344 real engine/kernel bugs.

## Scoring
Base: executable (PoC triggers the bug; patch evaluated against gold +
harness). Pro: LLM-based judge for PoC correctness (demonstrated need —
rule-based judges misgrade).

## Fit for Shlepa
- **Overlap:** **highest of the vuln batch** — patching maps 1:1 to
  `contest-fix-sqli-*`; PoC generation maps to `contest-find-sqli-login`.
  The whole "vulnerable repo + harness + gold patch" case structure mirrors
  our Harbor task layout.
- **Offline feasibility:** high — isolated environments, local.
- **Adaptation cost:** medium — their instance generator ($0.87/instance)
  can **manufacture new fix/find tasks for our dev loop** instead of
  hand-authoring: generate a repo+bug+patch, wrap as a Harbor task.
- **Recommendation:** **second-priority adaptation** (after CrackMeBench).
  Best lever: use the generator as a *task factory* for
  `bench-sec-bench-*` find/fix pairs. Study the gold-patch evaluation
  approach for our fix-task verifiers.

## Sources
- Paper: https://arxiv.org/abs/2506.11791
- Pro paper: https://arxiv.org/abs/2605.26548
- Code: https://github.com/SEC-bench/SEC-bench
