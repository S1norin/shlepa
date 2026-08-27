# SecBench

- **Category:** knowledge (cybersecurity QA dataset)
- **Source:** arXiv 2412.20787, 2024
- **Paper:** https://arxiv.org/abs/2412.20787 (PDF: `papers/secbench.pdf`)
- **Data:** Hugging Face (per paper; large dataset — do not bulk-download
  into the repo)
- **Reviewed:** 2026-08-27

## What it tests
LLM performance in the **cybersecurity domain**: **44,823 MCQs + 3,087
short-answer questions**, deliberately multi-dimensional: question formats
(MCQ/SAQ), capability levels (**knowledge retention vs logical
reasoning**), languages (Chinese + English), and multiple security
sub-domains. Built from open sources plus a Cybersecurity Question Design
Contest.

## Environment
Static dataset; any model endpoint; fully offline; cheap to score.

## Tasks
Domain QA across security sub-domains.

## Scoring
Exact match / MCQ accuracy; SAQ scoring per paper.

## Fit for Shlepa
- **Overlap:** foundational knowledge only; says nothing about tool use,
  multi-step investigation, or task completion.
- **Offline feasibility:** excellent.
- **Adaptation cost:** low (subset sampling).
- **Recommendation:** at most a *model-selection screen* (e.g. 500-item
  stratified slice). The source list itself cautions it "shouldn't be your
  primary agent benchmark" — confirmed. Not worth adapting into Harbor
  tasks.

## Sources
- Paper: https://arxiv.org/abs/2412.20787
