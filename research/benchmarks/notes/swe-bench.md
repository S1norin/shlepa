# SWE-bench (+ "security extensions")

- **Category:** general software engineering (issue resolution)
- **Source:** Princeton, arXiv 2310.06770, 2023
- **Paper:** https://arxiv.org/abs/2310.06770 (PDF: `papers/swe-bench.pdf`)
- **Code:** https://github.com/SWE-bench ·
  https://github.com/SWE-agent/mini-swe-agent
- **Reviewed:** 2026-08-27

## What it tests
Resolving **real GitHub issues** from open-source repos: 2,294 issue-PR
pairs from 12 popular Python repositories; the agent gets the repo at the
pre-fix commit + issue text and must produce a patch; **SWE-bench Lite**
(300) and **Verified** (500, human-validated) subsets standardize
evaluation. The reference to "security extensions" in our source list
points at the general idea (fix bugs without introducing vulnerabilities,
detect pre-existing vulns) — the specific name **VulnAgentBench could not
be verified on arXiv or GitHub (unverified; likely a model hallucination
in the source list)**. Verified security-adjacent work instead: SEC-bench
(patching with gold patches), CyberGym (PoC at scale), VulBench/VND-style
datasets.

## Environment
Per-task container with the Python repo checked out; agent edits code and
runs commands; **hidden test suite** (pass-to-pass + fail-to-pass tests)
scores the patch deterministically. Fully offline.

## Tasks
Issue → patch: bug fixes, feature requests, refactors; mixed difficulty.

## Scoring
Executable: generated patch must make fail-to-pass tests pass and keep
pass-to-pass tests passing. Resolution rate @k.

## Fit for Shlepa
- **Overlap:** the *fix* half — `contest-fix-sqli-*` is essentially
  SWE-bench-style issue resolution (find + patch a bug in a small app).
  **mini-swe-agent** (confirmed: "100-line AI agent… >74% on SWE-bench
  verified") is worth reading as a minimal agent-loop reference for our
  architecture work — though Shlepa's loop is already similar.
- **Offline feasibility:** excellent.
- **Adaptation cost:** medium — SWE-bench tasks are Python-repo sized;
  our container budget (2 GB RAM, few minutes) fits small issues.
- **Recommendation:** not a direct eval target (our tasks are the
  domain-specific version), but: (1) the **hidden-test verifier pattern**
  is exactly our `test.sh` model — keep it; (2) optionally adapt 2–3 small
  security-adjacent SWE-bench issues as agent-capability probes; (3) read
  mini-swe-agent as architecture input (see research/notes/ later).

## Sources
- Paper: https://arxiv.org/abs/2310.06770
- SWE-bench: https://github.com/SWE-bench
- mini-swe-agent: https://github.com/SWE-agent/mini-swe-agent
