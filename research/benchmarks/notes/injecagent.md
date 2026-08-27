# InjecAgent

- **Category:** agent-security (indirect prompt injection, tool poisoning)
- **Source:** arXiv 2403.02691, 2024 (NUS + others)
- **Paper:** https://arxiv.org/abs/2403.02691 (PDF: `papers/injecagent.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Vulnerability of **tool-integrated LLM agents to indirect prompt injection
(IPI)**: malicious instructions embedded in external content (tool
results) that the agent processes. Covers two attack-intention classes:
**direct harm to the user** and **exfiltration of private data**.

## Environment
Benchmark harness (Python) with simulated user tools and attacker tools;
the agent runs its normal tool loop while attacker instructions arrive
through tool outputs. Local/offline.

## Tasks
**1,054 test cases** across **17 user tools and 62 attacker tools**
(poisoned tool descriptions + injected tool results).

## Scoring
Attack success rate per intent class; 30 LLM agents evaluated. Headline:
ReAct-prompted GPT-4 was attacked successfully **24%** of the time;
reinforcing attacker instructions with a "hacking prompt" nearly doubles
ASR.

## Fit for Shlepa
- **Overlap:** same pillar as AgentDojo (agent self-security), but
  *poisoned tool descriptions* add a second injection surface beyond
  data: our agent's tool schema/descriptions could be the vector (e.g.
  malicious file metadata read as "context").
- **Offline feasibility:** excellent.
- **Adaptation cost:** low for the pattern — poison a fixture (file
  contents / log lines / git commit messages) in an existing Harbor task
  variant; score ASR alongside reward.
- **Recommendation:** use as the **recipe for injection variants** of our
  tasks (cheaper than running its full 1,054-case suite); pair with
  AgentDojo for the reporting model. Lower priority than AgentDojo itself.

## Sources
- Paper: https://arxiv.org/abs/2403.02691
