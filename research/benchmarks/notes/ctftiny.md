# CTFTiny (+ CTFJudge / CTF Competency Index)

- **Category:** ctf (rapid iterative evaluation) + agent-architecture
- **Source:** arXiv 2508.05674, 2025 — "Towards Effective Offensive Security
  LLM Agents: Hyperparameter Tuning, LLM as a Judge, and a Lightweight CTF
  Benchmark" (the paper DeepSeek listed under that title; CTFTiny is its
  benchmark)
- **Paper:** https://arxiv.org/abs/2508.05674 (PDF: `papers/ctftiny.pdf`)
- **Code:** https://github.com/NYU-LLM-CTF/CTFTiny ·
  https://github.com/NYU-LLM-CTF/CTFJudge
- **Reviewed:** 2026-08-27

## What it tests
Two things in one paper:
1. **Factors driving offensive-security agent success** — LLM
   hyperparameters (temperature, top-p, max token length), multi-agent
   coordination settings, task planning.
2. **CTFTiny**: a curated benchmark of **50 representative CTF challenges**
   across binary exploitation, web, reverse engineering, forensics, and
   cryptography — sized for *rapid* iterative agent evaluation.

Also introduces **CTFJudge**: an LLM-as-a-judge framework that analyzes
agent **trajectories** and scores granular CTF solving steps, and **CCI
(CTF Competency Index)**: a partial-correctness metric measuring how closely
an agent solution aligns with human-crafted gold standards.

## Environment
50 challenge environments from the NYU CTF ecosystem (Docker-based, mixed
local/server); agent runs standard agentic loops against them.

## Tasks
50 curated challenges, cross-category, representative of the field.

## Scoring
Dual: binary flag-based pass@k **plus** CCI partial credit from trajectory
analysis against gold-standard solutions.

## Fit for Shlepa
- **Overlap:** web/forensics/binary items map to our vuln and incident
  families.
- **Offline feasibility:** high (Docker challenges; pick the
  no-internet-subset).
- **Adaptation cost:** low — same shape as NYU CTF Bench; smaller and
  curated, so faster to bring a dev-eval set from the repo.
- **Recommendation:** **top candidate for the dev "proving ground"** — 50
  challenges is the right iteration size. Steal **CCI-style trajectory
  scoring** for our dev runs: we currently log only binary `reward`, and
  CCI would give graded progress on the hard tasks (same motivation as
  DeepRed's checkpoints).

## Sources
- Paper: https://arxiv.org/abs/2508.05674
- CTFTiny: https://github.com/NYU-LLM-CTF/CTFTiny
- CTFJudge: https://github.com/NYU-LLM-CTF/CTFJudge
