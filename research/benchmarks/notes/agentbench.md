# AgentBench

- **Category:** general agent capability (non-security)
- **Source:** ICLR 2024, arXiv 2308.03688
- **Paper:** https://arxiv.org/abs/2308.03688 (PDF: `papers/agentbench.pdf`)
- **Code:** https://github.com/THUDM/AgentBench
- **Reviewed:** 2026-08-27

## What it tests
**LLMs as agents** across 7 interactive environments: operating system
(bash), database (SQL), knowledge graph, decentralized knowledge (card
game), single-algorithm puzzle, household (AlfWorld), web shopping
(WebShop). ~250 tasks measuring decision-making, tool use, and reasoning
in interactive loops — independent of any security domain.

## Environment
Per-domain simulated environments (Docker for OS/DB); agent acts via
text/commands, observes, repeats; all offline.

## Tasks
Task families per domain with rule-based success checks.

## Scoring
Rule-based success rate per domain + action-validity rate.

## Fit for Shlepa
- **Overlap:** agent competence pillar, not cyber. The **OS (bash) and DB
  (SQL) domains** are the closest to our container agent's daily
  operations (shell + app + query-like tasks).
- **Offline feasibility:** excellent.
- **Adaptation cost:** low for OS/DB slices; the harness is its own loop,
  so use it as a model screen, not inside our agent.
- **Recommendation:** optional **regression screen for model swaps**
  (OS/DB slices) to detect when a new base model is worse at basic
  tool-use. Don't invest in adapting it — our security tasks already
  measure tool use in-domain.

## Sources
- Paper: https://arxiv.org/abs/2308.03688
- Code: https://github.com/THUDM/AgentBench
