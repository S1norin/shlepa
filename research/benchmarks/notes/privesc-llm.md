# PrivEsc-LLM (local model post-training for privesc)

- **Category:** agent-construction (local small model) — not a benchmark
- **Source:** arXiv 2603.17673, 2026 — "Towards Reliable Local Security
  Agents: Verifiable Post-Training for Linux Privilege Escalation"
- **Paper:** https://arxiv.org/abs/2603.17673 (PDF: `papers/privesc-llm.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
How to turn a **small local model into a security agent** under strict
resource constraints: Linux privilege escalation as the representative
task (automatically verifiable + multi-step interactive reasoning).
Two-stage post-training: (1) **SFT on traces from procedural
privesc environments**, (2) **RL with verifiable rewards**. Setup
deliberately mitigates data leakage.

## Environment
Procedural Linux privesc environments (training + a held-out benchmark of
12 scenarios; 20-interaction-round budget).

## Tasks
12 held-out Linux privilege-escalation scenarios (interactive shell).

## Scoring
Verifiable reward (escalation achieved or not); SFT doubles baseline
success under the 20-round budget; PrivEsc-LLM 4B reaches **93.3%
success**, behind only Claude Opus 4.7 at that budget. (The source list
cited ~95.8% — close; the v2 abstract says 93.3%.)

## Fit for Shlepa
- **Overlap:** this is the "small local model" pillar: proof that a 4B
  local model can nearly match frontier models on a verifiable security
  task *with the right post-training* (SFT on agent traces + RL with
  verifiable rewards).
- **Recommendation:** **key architecture input**, not an eval target. If
  the project ever moves toward a local/fine-tuned model (cost, latency,
  air-gap reasons), this is the recipe to follow: procedural envs →
  trace SFT → RL on verifiable rewards. Our Harbor tasks + verifiers are
  exactly the "procedural environment with verifiable reward" substrate
  it needs. File a backlog issue if local-model work gets prioritized.

## Sources
- Paper: https://arxiv.org/abs/2603.17673
