# CyberGym

- **Category:** vuln-exploit (real-world vulnerability analysis at scale)
- **Source:** arXiv 2506.02548, 2025
- **Paper:** https://arxiv.org/abs/2506.02548 (PDF: `papers/cybergym.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Given a vulnerability's **text description and the corresponding codebase**, the
agent must generate a **proof-of-concept test that reproduces the
vulnerability**. 1,507 real-world vulnerabilities across 188 open-source
projects (curl, ffmpeg, openssl, nginx, tor, qemu, ...). Even the best
agent+model combinations reach only ~20% success rate. The benchmark also
produced real impact: 34 zero-day findings and 18 historically incomplete
patches. Adjustable to different vulnerability-analysis settings.
Follow-up: **CyberGym-E2E** (arXiv 2606.04460), end-to-end variant.

## Environment
Modular, **containerized** design (one container per instance) built on
**ARVO** — reusable Docker images of OSS-Fuzz vulnerabilities. Provides the
pre-patch program executable (where the PoC must trigger) and post-patch
executables (where it must not). Data-contamination effects are studied
explicitly. Fully local-deployable in principle; the full dataset is large
(~240 GB reported by community sources — unverified, check before planning).

## Tasks
Repository-level vulnerability reproduction from description; single-task
instances, each an independent repo + vuln pair. No CTF flag mechanics.

## Scoring
Executable and deterministic: the generated PoC test is run against the
pre-patch build (must demonstrate the bug) and post-patch build (must not).
Binary solved/unsolved per instance.

## Fit for Shlepa
- **Overlap:** strongest of all researched benchmarks with the *vulnerability
  finding* contest family (`contest-find-sqli-login` style: code analysis →
  confirmed finding). The "description + codebase → reproducible PoC" framing
  is exactly a security-agent core skill.
- **Offline feasibility:** high per instance (self-contained containers);
  storage is the only real cost.
- **Adaptation cost:** low-to-medium — one instance ≈ one Harbor task
  (`bench-cybergym-<project>`): Dockerfile = ARVO image, instruction = vuln
  description, test.sh = run PoC on pre/post-patch.
- **Recommendation:** do NOT run the full set locally. Port a small subset
  (e.g. 3–5 instances covering C, Go, Python projects) as dev tasks, and use
  the per-instance container model as our template for vuln-finding tasks.

## Sources
- Paper: https://arxiv.org/abs/2506.02548
- CyberGym-E2E: https://arxiv.org/abs/2606.04460
- ARVO (OSS-Fuzz images): https://arxiv.org/abs/2401.03964
