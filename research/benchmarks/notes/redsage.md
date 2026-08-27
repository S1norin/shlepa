# RedSage / RedSage-Bench

- **Category:** knowledge (cybersecurity generalist) + local-model training
- **Source:** arXiv 2601.22159, 2026
- **Paper:** https://arxiv.org/abs/2601.22159 (PDF: `papers/redsage.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Two deliverables in one paper:
1. **RedSage** — an open-source, **locally deployable cybersecurity
   assistant LLM**: 11.8B tokens of curated cybersecurity continual
   pretraining (28.6K documents: frameworks, offensive techniques,
   security tools) + an agentic augmentation pipeline producing **266K
   multi-turn cybersecurity SFT samples**.
2. **RedSage-Bench** — **30K multiple-choice + 240 open-ended Q&A items**
   covering cybersecurity knowledge, skills, and tool expertise.

## Environment
Benchmark = static QA sets, offline. The model itself targets local
deployment (privacy: no proprietary API exposure).

## Tasks
Knowledge MCQ, skill/tool-expertise open-ended QA.

## Scoring
Standard QA scoring; model also evaluated on established cyber benchmarks
(see paper).

## Fit for Shlepa
- **Overlap:** knowledge baseline only — QA, not agentic behavior.
- **Offline feasibility:** excellent.
- **Adaptation cost:** low for QA subsets.
- **Recommendation:** low priority for Shlepa the *agent*; **high interest
  for Shlepa the *model***: if we ever fine-tune a small local model
  (the PrivEsc-LLM/Hackphyr direction), RedSage's data curation + agentic
  SFT pipeline is a concrete, recent recipe. Use a RedSage-Bench slice as
  the capability regression test for such a model, not for the agent.

## Sources
- Paper: https://arxiv.org/abs/2601.22159
