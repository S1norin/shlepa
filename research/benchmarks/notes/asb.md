# ASB — Agent Security Bench

- **Category:** agent-security (comprehensive attacks+defenses framework)
- **Source:** arXiv 2410.02644, 2024
- **Paper:** https://arxiv.org/abs/2410.02644 (PDF: `papers/asb.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
A **formalized, comprehensive** evaluation of attacks and defenses for
LLM-based agents: 10 scenarios (e-commerce, autonomous driving, finance,
...), 10 agents, **400+ tools**, 27 attack/defense methods, 7 metrics.
Benchmarked: 10 prompt-injection attacks, **memory poisoning**, a
**Plan-of-Thought backdoor attack**, 4 mixed attacks, 11 defenses, across
13 LLM backbones.

## Environment
Scenario sandboxes with tools and memory mechanisms; attacks target
multiple agent stages — system prompt handling, user prompt handling, tool
usage, and **memory retrieval** (memory poisoning is a first-class attack).

## Tasks
Scenario tasks per environment + attack/defense test matrix.

## Scoring
7 evaluation metrics (incl. a newly introduced one for agent security);
headline: highest average **attack success rate 84.30%**, current defenses
show limited effectiveness.

## Fit for Shlepa
- **Overlap:** agent self-security pillar; the **memory-poisoning** angle
  is the one our other notes don't cover and is directly relevant if Shlepa
  ever gains persistent memory across tasks.
- **Offline feasibility:** high (scenario sandboxes).
- **Adaptation cost:** medium — large matrix; not something to run in
  full in our dev loop.
- **Recommendation:** keep as a **threat-model catalog** — its attack-stage
  taxonomy (system prompt / user prompt / tool use / memory) is the right
  checklist when auditing Shlepa's own prompt construction and when
  designing adversarial task variants. Not a dev-eval target.

## Sources
- Paper: https://arxiv.org/abs/2410.02644
