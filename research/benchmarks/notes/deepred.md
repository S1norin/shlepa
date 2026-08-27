# DeepRed ("Do Agents Dream of Root Shells?")

- **Category:** ctf (offensive, virtualized)
- **Source:** arXiv 2604.19354, 2026
- **Paper:** https://arxiv.org/abs/2604.19354 (PDF: `papers/deepred.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
LLM-based agents on **realistic CTF challenges in isolated virtualized
environments**: 10 VM-based CTF challenges spanning different categories,
benchmarked across ten commercially accessible LLMs. Best model: **35%
average checkpoint completion** — agents are weakest on non-standard
discovery and longer-horizon adaptation.

## Environment
Agent sits in a **Kali Linux attacker VM** with terminal tools and optional
web search, connected over a **private network** to a target challenge VM.
Full execution traces are recorded. Two-VM topology (attacker + target) is
heavier than a single-container setup.

## Tasks
10 VM-based CTF challenges (mixed categories). No CTF flag is required —
progress is checkpointed (below).

## Scoring
**Partial credit**: each challenge has checkpoints derived from public
writeups; completion is assigned by an automated **summarise-then-judge
pipeline** that reads the agent's execution logs (LLM-assisted but grounded
in traces, not free-form judging of the final answer).

## Fit for Shlepa
- **Overlap:** CTF ≠ current contest families, but the forensics/pwn
  challenge types sit adjacent to `contest-incident-log-forensics` and
  vuln-finding tasks.
- **Offline feasibility:** medium — VMs per challenge; optional web search
  must be disabled for offline runs (fine).
- **Adaptation cost:** medium — the two-VM topology is more than our
  single-container dev loop, though a single container with local services
  can emulate many attacker→target setups.
- **Recommendation:** borrow the **partial-credit method** (checkpoints from
  writeups + trace-grounded judge) — our `reward.txt` is binary 0/1 and
  partial credit would massively improve dev-loop signal on hard tasks.
  Optionally adapt 1–2 forensics challenges as `bench-deepred-*` tasks.

## Sources
- Paper: https://arxiv.org/abs/2604.19354
- Code: open-source per abstract (repo linked in paper; verify URL before
  citing in an issue)
