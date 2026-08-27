# AgentDojo

- **Category:** agent-security (prompt injection against tool-using agents)
- **Source:** ETH Zurich (SpyLab) + Invariant Labs, arXiv 2406.13352, 2024
- **Paper:** https://arxiv.org/abs/2406.13352 (PDF: `papers/agentdojo.pdf`)
- **Code:** https://github.com/ethz-spylab/agentdojo (`pip install agentdojo`,
  active; results: https://agentdojo.spylab.ai/results/)
- **Reviewed:** 2026-08-27

## What it tests
**Adversarial robustness of agents that execute tools over untrusted data**:
indirect prompt injection, where data returned by tools (emails, web
pages, files) hijacks the agent into malicious actions. Deliberately an
**extensible dynamic environment**, not a static test suite — new tasks,
defenses, and adaptive attacks are first-class.

## Environment
Local Python package: each task = a sandboxed tool environment (simulated
bank, mail server, travel API, ...); attack/defense paradigms from the
literature built in (incl. a prompt-injection detector via the
`transformers` extra). No external internet required.

## Tasks
**97 realistic tasks** (email client, e-banking, travel bookings, smart
home, Slack-like tools) + **629 security test cases** (attack scenarios per
task).

## Scoring
Two axes measured simultaneously: **utility** (benign task success) and
**attack success rate (ASR)** per security property. Key findings: SOTA
LLMs fail many tasks even with no attacks; existing injections break some
security properties, not all — the framework supports studying trade-offs
rather than one number.

## Fit for Shlepa
- **Overlap:** this is the "security of the agent itself" pillar from the
  source list — for an offline security agent, untrusted *inputs* (logs,
  files, tool output, code comments) are exactly where injections would
  land (e.g. a poisoned log line in a forensics task).
- **Offline feasibility:** **excellent** — local package, simulated
  backends, runs with our `--network host` or none.
- **Adaptation cost:** medium to run as-is (it ships its own agent loop);
  low for the **pattern**: our Harbor tasks can carry an *adversarial
  variant* — same task + injected hostile instructions in a fixture —
  scored as (reward, ASR) instead of reward alone.
- **Recommendation:** **highest-value agent-security reference.** Two
  concrete moves: (1) add 1–2 injection-laden variants of our forensics
  task as dev probes; (2) adopt the utility×ASR reporting pair for any
  adversarial eval we build.

## Sources
- Paper: https://arxiv.org/abs/2406.13352
- Code: https://github.com/ethz-spylab/agentdojo
