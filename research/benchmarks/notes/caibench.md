# CAIBench (Cybersecurity AI Benchmark)

- **Category:** general (meta-benchmark of cyber AI capability)
- **Source:** arXiv 2510.24317, 2025
- **Paper:** https://arxiv.org/abs/2510.24317 (PDF: `papers/caibench.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
A **modular meta-benchmark** evaluating models *and agents* across
offensive and defensive cyber domains, with 5 categories / 10,000+
instances: **Jeopardy-style CTFs, Attack-and-Defense CTFs, Cyber Range
exercises, knowledge benchmarks, privacy assessments** (CyberPII-Bench).
Key finding: **pre-trained cyber knowledge does not imply attack/defense
ability** — knowledge and capability are measured separately. Novel
pieces: systematic simultaneous offensive-defensive evaluation,
robotics-focused cyber challenges (RCTF2), privacy-preserving performance
assessment.

## Environment
Per-module environments (CTF targets, cyber ranges, QA sets); modules are
pluggable — pick a subset without taking the whole.

## Tasks
Per-module task inventory (CTF challenges, range scenarios, QA, PII
privacy). SOTA evaluation reveals **saturation** in several modules.

## Scoring
Per-module scoring; meta-level aggregation across offense/defense/knowledge/privacy.

## Fit for Shlepa
- **Overlap:** breadth overview — useful for keeping the research radar
  up to date, not a dev tool. The knowledge-vs-capability gap finding
  matches our own situation (model may "know" SQLi but fail to find it).
- **Offline feasibility:** module-dependent; mostly local.
- **Adaptation cost:** n/a as a whole; individual modules are other
  benchmarks (already covered in this directory).
- **Recommendation:** **watch item** — track it for new modules
  (especially cyber-range-style exercises and A/D CTFs, closest to
  "agent does a job" evaluation). No direct adaptation.

## Sources
- Paper: https://arxiv.org/abs/2510.24317
