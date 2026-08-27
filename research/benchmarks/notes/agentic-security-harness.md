# Agentic Security Harness

- **Category:** agent-security (defensive boundary testing) — infra
- **Source:** github.com/krivonosoff161/agentic-security-harness (v1.2.0,
  Apache-2.0, PyPI `agentic-security-harness`; very active — pushed 2026-08-26)
- **Code:** https://github.com/krivonosoff161/agentic-security-harness
- **Reviewed:** 2026-08-27

## What it tests
**Defensive testing of agentic AI boundary failures**: "Your AI coding
agent reads untrusted repository text. Can it keep data separate from
instructions and authority?" — checks whether agents keep repo text,
tools, memory, and audit trails **inside their authority boundaries**.
Design principles match the source list exactly: local, deterministic,
trace-first, offline, reproducible.

## Environment
Local synthetic scenarios; compares a **deliberately vulnerable local
agent with a protected one**; records **portable traces and scorecards**;
outputs remediation reports. `pip install agentic-security-harness==1.2.0`
then `ash quickstart`. OpenSSF best-practices badge, CI + CodeQL.

## Tasks
Reproducible synthetic boundary scenarios (injected instructions in repo
text/tool output/memory; authority-limit tests).

## Scoring
Scorecards per scenario + replayable evidence ("the agent behaved
unsafely" → replay/validate/compare/review).

## Fit for Shlepa
- **Overlap:** agent self-security pillar; the "data vs instructions" and
  "authority boundary" framing maps onto our untrusted-input variants
  (poisoned logs/files in forensics tasks).
- **Offline feasibility:** excellent by design.
- **Adaptation cost:** low — pip-installable, no infra.
- **Recommendation:** **run its quickstart against Shlepa's agent loop**
  as an ad-hoc self-security probe (cheap, local, deterministic); study
  the trace/scorecard format as inspiration for our own adversarial
  variant scoring. Provenance caveat: single-maintainer project, no paper
  — indicative, not citable as a standard.

## Sources
- Repo: https://github.com/krivonosoff161/agentic-security-harness
