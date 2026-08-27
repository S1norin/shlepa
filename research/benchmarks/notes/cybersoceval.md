# CyberSOCEval

- **Category:** soc (malware analysis + threat-intelligence reasoning)
- **Source:** Meta AI, part of **CyberSecEval 4**, arXiv 2509.20166, 2025
- **Paper:** https://arxiv.org/abs/2509.20166 (PDF: `papers/cybersoceval.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
LLM capability on **two core defensive SOC tasks** with inadequate coverage
in existing benchmarks: **malware analysis** and **threat-intelligence
reasoning** — interpreting raw samples/reports, identifying techniques,
correlating indicators, prioritizing. Open source, explicitly motivated by
real SOC workload (alert/CTI deluge) rather than academic CTF-style tasks.

## Environment
Benchmark suite (task sets + evaluation scripts) within the CyberSecEval 4
framework; tasks are data-centric (samples/reports/indicators) rather than
live-environment agentic tasks — model answers are scored against ground
truth. (Agentic long-horizon SOC work is better covered by CTI-REALM /
SOCBench; this is the capability layer.)

## Tasks
Two task families: malware analysis (static/sample reasoning) and CTI
reasoning (indicator/technique correlation).

## Scoring
Task-specific ground-truth grading within the CyberSecEval 4 suite.
Findings: larger/modern LLMs perform better (scaling laws hold);
**reasoning models with test-time scaling do NOT get the coding/math-style
boost** — these models haven't been trained for this domain.

## Fit for Shlepa
- **Overlap:** capability baseline for the defensive half (our forensics
  task); malware analysis itself is not a current contest family.
- **Offline feasibility:** high — data-centric, local scoring.
- **Adaptation cost:** low-to-medium for individual tasks; full suite is
  CyberSecEval 4's machinery.
- **Recommendation:** use as a **knowledge baseline** (cheap, fast,
  model-selection signal) — not the primary agent benchmark. The
  "test-time scaling doesn't transfer to SOC domains" finding is directly
  relevant when we choose reasoning settings for Shlepa.

## Sources
- Paper: https://arxiv.org/abs/2509.20166
- Parent suite: CyberSecEval 4 (see `cyberseceval.md` note)
