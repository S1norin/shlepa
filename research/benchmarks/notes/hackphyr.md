# Hackphyr (local fine-tuned red-team agent)

- **Category:** agent-construction (local fine-tuned model) — not a benchmark
- **Source:** arXiv 2409.11276, 2024 — "Hackphyr: A Local Fine-Tuned LLM
  Agent for Network Security Environments"
- **Paper:** https://arxiv.org/abs/2409.11276 (PDF: `papers/hackphyr.pdf`)
- **Code:** no dedicated repo found; evaluation environment: NetSecGame
  (https://github.com/stratosphereips/NetSecGame)
- **Reviewed:** 2026-08-27

## What it tests
A **locally fine-tuned 7B red-team agent** for network security
environments (built on Zephyr-class base, runs on a single GPU):
penetration-testing behavior — planning, tool interaction, multi-step
exploitation — with a **new task-specific cybersecurity dataset**
generated to enhance the base model.

## Environment
Network security environments (CTF-style targets); local inference, no
cloud LLM (motivation: privacy, cost, connectivity).

## Tasks
Complex, previously unseen penetration scenarios (planning + execution).

## Scoring
Task success in the environments; behavior analysis (planning quality,
shortcomings). Findings: comparable to GPT-4 on these tasks, clearly
above GPT-3.5-turbo and Q-learning baselines.

## Fit for Shlepa
- **Overlap:** same pillar as PrivEsc-LLM (small local models via
  domain fine-tuning), earlier-generation work; the **task-specific
  dataset construction** and agent-behavior analysis are the reusable
  parts.
- **Recommendation:** read for the dataset-construction method and the
  behavior-analysis taxonomy; PrivEsc-LLM (2026) is the more current
  recipe (SFT+RL, verifiable rewards). Both support: *domain-specific
  post-training is how small models reach useful security capability* —
  relevant to any future local-model decision.

## Sources
- Paper: https://arxiv.org/abs/2409.11276
- Environment: https://github.com/stratosphereips/NetSecGame
