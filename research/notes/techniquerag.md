# TechniqueRAG (Lekssays et al., 2025)

- **Paper:** "TechniqueRAG: Retrieval Augmented Generation for Adversarial
  Technique Annotation in Cyber Threat Intelligence Text"
  (arXiv:2505.11988) — `research/papers/2025-lekssays-techniquerag.pdf`
- **Category:** rag / technique annotation (review for issue #89)
- **Reviewed:** 2026-09-03

Question: can a RAG pipeline over the ATT&CK KB reliably map incident text
to exact (sub-)technique IDs, and which part of the pipeline (retriever vs
re-ranker vs generator) carries the accuracy?

## Method

Three modules (pp. 2–5):

1. **Retriever R** — any off-the-shelf retriever; they use **BM25 with
   K=40** candidates from a corpus of ~10K text→technique annotation
   pairs (p. 4: an off-the-shelf sparse or dense retriever is used because
   fine-tuning the retriever without hard negatives is sub-optimal; setup
   p. 5).
2. **Re-ranker R̂** — a *frozen* instruction-tuned LLM (DeepSeek v3,
   temperature 0) with a domain-specific structured-CoT prompt: decompose
   the query into attack steps → map to tactics → map to techniques →
   pick the finest sub-technique, with explicit confidence per candidate
   (pp. 4–5). Sliding window over the 40 candidates (batches of 40,
   overlap 20), keeps top k=3 (p. 5).
3. **Generator G** — Ministral-8B-Instruct fine-tuned with LoRA
   (r=8, α=4, lr 1e-4) on the annotation pairs, **constrained to emit IDs
   only from the re-ranked candidate set** to suppress hallucination
   (p. 5).

## Results (technique / sub-technique level, single-label benchmarks)

- Technique F1 (Table 2, p. 6): TechniqueRAG **74.02 (Tram)**,
  **91.09 (Procedures)** vs GPT-4o+RAG 62.16 / 78.82 and GPT-4o direct
  43.35 / 57.04. Sub-technique F1 (Table 3, p. 7): **88.11 (Procedures)**
  vs NCE 73.74.
- BM25 alone on the multi-label Expert set: P@1 **51.6%** technique /
  45.9% sub-technique; the LLM re-ranker alone raises P@1 to **71.3 /
  66.9** (Table 4, p. 8) — the re-ranking step, not the retriever,
  carries most of the accuracy.
- RAG augmentation (retrieved exemplars) improves *all* generative
  models; without fine-tuning the open-LLM gain is modest (Ministral
  RAG 30.39 → 42.22 F1 Expert, §5.3, p. 7) — fine-tuning matters where
  you can fine-tune.
- Error analysis (p. 8): under-prediction of co-occurring techniques;
  confusion among sub-techniques of one technique (T1059.\*);
  parent/child confusion and **invalid sub-technique IDs**; class
  imbalance (23% of techniques have >50 training samples).

## Applicability to Shlepa

- Shlepa's graders do exactly this task: string-match
  `primary_mitre_technique` in `report.json` against expected IDs
  (single-label technique/sub-technique prediction ≈ their Tram /
  Procedures setting).
- Shlepa **cannot fine-tune** the generator (fixed contest model). The
  transferable design is: **retrieval + LLM reasoning over a small
  candidate set** — the agent loop *is* the re-ranker: query the KB →
  top-K candidates with descriptions → reason (the paper's
  steps→tactics→technique→sub-technique decomposition is a ready-made
  prompt recipe for the arm-gated prompt snippet) → refine the query if
  the top candidates don't fit the evidence.
- The "constrain to the candidate set" anti-hallucination finding maps to
  the KB tool returning only matching rows (the agent can only cite IDs
  it has seen) plus an old→new alias map for renumbered IDs (T1562.001 →
  T1685).
- The error analysis supports the KB layout: show parent + sub-technique
  rows together (parent/child confusion), carry tactic labels
  (tactic-family confusion), and validate emitted IDs against the KB.
- BM25 being a strong off-the-shelf baseline in this exact domain
  supports option (b) in `mitre-rag-survey.md`.

## Benchmarks

Tram (198 unique techniques), Procedures (488), Expert (290, multi-label);
~10K annotated examples public in total (p. 2: "despite MITRE ATT&CK
framework defines over 550 adversarial (sub-)techniques, only
approximately 10,000 annotated examples are publicly available").
