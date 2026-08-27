# AgentRE-Bench

- **Category:** reverse-engineering (long-horizon agentic)
- **Source:** github.com/agentrebench/AgentRE-Bench (no arXiv paper found)
- **Code:** https://github.com/agentrebench/AgentRE-Bench
- **Reviewed:** 2026-08-27

## What it tests
LLM agents on **long-horizon reverse-engineering tasks**: given a compiled
binary (no source), identify C2 infrastructure, encoding schemes,
anti-analysis techniques, process-injection behavior, and communication
protocols. Measures planning, tool selection, interpretation of raw tool
output (hex dumps, disassembly), and budget management (**25 tool calls**).

## Environment
Linux/Unix (ELF x86-64) and Windows (PE32+ x86-64). Static-analysis
toolset appropriate to the platform. All 23 levels are **synthetic**:
compiled from purpose-built C/C++ sources with known ground truth
(deterministic judging, no licensing/ethics issues, reproducible).

## Tasks
23 levels with controlled difficulty progression: plaintext TCP shells →
XOR-encoded strings → anti-debugging → polymorphic shells → multistage
payloads → PE injection, direct syscalls, advanced evasion, synthetic
ransomware worm (level 13 requires ~5 chained sub-identifications and 18
technique tags). Chains of 10–25 tool calls where each output informs the
next decision.

## Scoring
**Fully deterministic**: weighted fields + Jaccard overlap for set
comparisons; hallucinated techniques penalized (−0.05 per false claim). No
LLM judge. V3 Windows-PE results in-repo (6 frontier models, stripped vs
unstripped).

## Fit for Shlepa
- **Overlap:** binary RE is not a current contest family, but the measured
  skills (multi-step tool chaining, interpreting raw tool output, working
  under a call budget) are exactly the agent-capability skills the
  competition stresses under time/token limits.
- **Offline feasibility:** **excellent** — small synthetic binaries, local
  tools, no network, deterministic.
- **Adaptation cost:** low — one level ≈ one Harbor task
  (`bench-agentre-<level>`); ground truth → `tests/test.sh` check of the
  agent's structured answer.
- **Recommendation:** adapt a few easy/medium levels as agent-capability
  probes in the dev preset; their deterministic scoring model is a clean
  template for our verifiers.

## Sources
- Repo: https://github.com/agentrebench/AgentRE-Bench (107★, active as of
  2026-08)
