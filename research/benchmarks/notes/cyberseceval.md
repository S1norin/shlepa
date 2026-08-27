# CyberSecEval 2 / 3 (Meta)

- **Category:** knowledge / LLM-security (risk + capability suites)
- **Source:** Meta AI (Purple Llama)
- **Paper:** CSE2 https://arxiv.org/abs/2404.13161 (PDF:
  `papers/cyberseceval2.pdf`) · CSE3
  https://arxiv.org/abs/2408.01605 (PDF: `papers/cyberseceval3.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Wide-ranging **cybersecurity risks and capabilities** of LLMs:
- **CSE2** adds two areas: **prompt injection** and **code interpreter
  abuse**; introduces the **safety/utility tradeoff** quantified by
  **False Refusal Rate (FRR)** — over-defensive models that reject benign
  requests lose utility. Findings: 26–41% prompt-injection success across
  tested SOTA models (GPT-4, Llama 3, ...).
- **CSE3** assesses **8 risks in two categories** (risk to third parties;
  risk to developers/end users), adding offensive-capability areas:
  automated social engineering, scaling manual offensive operations,
  autonomous offensive cyber operations.

## Environment
Prompt-based test suites (no live agent environments); runnable offline
against any model endpoint.

## Tasks
QA/instruction-style risk tests (malware code, exploits, phishing,
social engineering, injection, refusal calibration).

## Scoring
Per-test pass/rate; FRR measures the refusal calibration explicitly.

## Fit for Shlepa
- **Overlap:** model-layer safety, not agent behavior — useful as a cheap
  *baseline screen* of whatever model powers Shlepa (refusal behavior on
  security tasks matters: an over-refusing model fails find-sqli tasks
  for safety reasons, an under-refusing one is a risk).
- **Offline feasibility:** excellent.
- **Adaptation cost:** low (prompt sets), but it measures the model, not
  our agent loop — keep it out of the main dev eval.
- **Recommendation:** run CSE2 injection + refusal sets once per model
  swap as a sanity screen; steal the **FRR metric** for our own
  adversarial task variants (correctly answering benign vs poisoned
  versions is exactly the tradeoff we'd report). The **CyberSOCEval**
  note covers the CSE4 defensive additions.

## Sources
- CSE2: https://arxiv.org/abs/2404.13161
- CSE3: https://arxiv.org/abs/2408.01605
- CSE4/SOC additions: see `cybersoceval.md`
