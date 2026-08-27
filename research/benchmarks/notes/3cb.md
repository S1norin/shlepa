# 3CB — Catastrophic Cyber Capabilities Benchmark

- **Category:** offensive-capability (capability/risk assessment)
- **Source:** arXiv 2410.09114, 2024
- **Paper:** https://arxiv.org/abs/2410.09114 (PDF: `papers/3cb.pdf` — 2-page
  announcement; full details in the repo)
- **Code:** https://github.com/apartresearch/3cb · packaged in UK AISI
  Inspect evals: https://ukgovernmentbeis.github.io/inspect_evals/evals/threecb/index.html
- **Reviewed:** 2026-08-27

## What it tests
**Real-world offensive cyber capabilities of LLM agents** as a
transparency/safety assessment tool: can frontier models perform offense
(reconnaissance → exploitation) across domains from **binary analysis to
web technologies**? Finding: frontier models (GPT-4o, Claude 3.5 Sonnet
era) can perform offensive tasks; smaller open-source models show limited
offensive capability.

## Environment
Curated **sandboxed/contained attack environments** per task (Docker-based
targets); offline-runnable; designed for model-provider and government use
in capability evaluations. 15 challenges **aligned to MITRE ATT&CK** with
80 elicitation configurations to find the best-performing setup per model
(robust evaluation against prompt sensitivity).

## Tasks
Offense pipeline tasks: reconnaissance, exploitation against contained
targets; spans binary and web domains.

## Scoring
Deterministic per-task success (target state checks); aggregates into an
offensive-capability profile per model.

## Fit for Shlepa
- **Overlap:** measures the offensive half (recon + exploit) of what our
  find-sqli family asks, at a capability-ceiling level.
- **Offline feasibility:** high — sandboxed targets, local.
- **Adaptation cost:** medium — targets are contained apps; wrapping one
  target = one Harbor task.
- **Recommendation:** low priority for competition prep (it's a
  capability-ceiling/risk benchmark, not a dev tool), but useful as a
  *threat-model* reference: the recon→exploit pipeline structure is a good
  checklist for designing adversarial/robustness variants of our tasks
  (see the agent-security batch notes).

## Sources
- Paper: https://arxiv.org/abs/2410.09114
- Code: https://github.com/facebookresearch/3cb
