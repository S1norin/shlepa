# NIST AI RMF — Generative AI Profile (governance reference)

- **Category:** governance/risk framework (not an executable benchmark)
- **Source:** NIST, publication NIST.AI.600-1, 2024
- **PDF:** https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
  (local copy: `papers/nist-ai-600-1.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Nothing executable — it is the **governance/evaluation framework** around
technical benchmarks: how to **identify, measure, and manage generative-AI
risk** (mapped onto the NIST AI RMF's four functions: GOVERN, MAP, MEASURE,
MANAGE). Adds GenAI-specific risk categories (e.g. privacy leakage,
information integrity, information security incl. prompt injection,
harmful content, value misalignment) and measurement guidance
(including when and how to use benchmarks, and their limitations).

## Environment
n/a (framework document).

## Tasks
n/a — provides risk categories, measurement principles, and a mapping of
existing evaluations to risk functions.

## Scoring
n/a.

## Fit for Shlepa
- **Overlap:** framing for the "is the agent safe in an offline
  environment" story: benchmark score ≠ safe; the profile gives the
  vocabulary (risk categories + measurement + management) to structure
  our self-security evaluation (agentdojo/injecagent/ASB results become
  MEASURE outputs against named risk categories).
- **Offline feasibility:** n/a.
- **Adaptation cost:** n/a.
- **Recommendation:** **reading, not running.** Keep on file; cite its
  risk-category list when writing the adversarial-variant design doc
  (each injection variant tags which risk category it exercises).

## Sources
- PDF: https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
- AI RMF main: https://www.nist.gov/itl/ai-risk-management-framework
