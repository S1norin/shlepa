# Hybrid fusion: why and how (RRF)

Reviewed: 2026-09-03

## Why hybrid

The measured failure modes of the two signals are complementary
(`analysis/bm25-baseline.md`):

- **BM25 (current tool)**: 100% on literal indicator queries
  (process names, API names, encodings) but P@5 20% on paraphrased SOC
  phrasings — it needs lexical overlap that natural incident language
  often does not provide.
- **Dense (expected, to be measured in #93)**: the reverse profile —
  good at paraphrase/behavioral similarity, weak on exact IDs, rare
  proper nouns, and fine-grained sub-technique distinctions (dense models
  routinely confuse T1543.003 with T1543.004-style siblings).

Fusing keeps BM25's precision on indicators while adding a recall path
for paraphrases.

## RRF (reciprocal rank fusion)

score(d) = Σ_i 1 / (k + rank_i(d)), standard k = 60.

- Rank-based → no score normalization between BM25 scores and cosine
  similarities.
- One hyperparameter; k=60 is the robust default (Cormack et al., 2009).
- `bench.py vectors --rrf-k 60` already computes the fused ranking
  against the same ground truth, so the hybrid number is free once the
  dense vectors exist.

## Fit with the existing pipeline

1. **Exact-ID stage unchanged** (first stage of `mitre_kb.py`): exact T-ID
   or alias (old→new) match short-circuits everything — graders
   string-match IDs, including old ones.
2. **Ranking stage**: RRF(BM25 over cheat corpus, dense over the same doc
   texts) → top-5 returned with name + cheat (current shape, no tool
   change for the agent).
3. **Re-query loop as LLM re-rank**: the agent already sees the top-5 and
   may re-query with refined terms. That loop is an LLM-in-the-loop
   re-rank; dense retrieval improves its *input* (the candidate set),
   which is where the measured 20% P@5 gap bites.

## Evidence from prior research

`research/notes/techniquerag.md` (TechniqueRAG, arXiv:2505.11988):
BM25 alone is decent for technique/sub-technique retrieval, but
**reranking substantially improves accuracy**. Two takeaways: (a) the
retrieval stage's candidate quality matters — a poor recall stage leaves
the re-rank (ours: the agent loop) nothing to fix; (b) hybrid + re-rank
is the pattern the field converges on, not "one signal wins".

## What would falsify this

If #93 shows dense P@5 ≤ BM25 P@5 on the paraphrase set (i.e., the
vanilla model's vectors add no paraphrase recall), the hybrid is
pointless for our query distribution and option F (semantic expansion)
alone is the play.

## Sources

- Cormack, Clarke, Buttler, "Reciprocal Rank Fusion outperforms
  Condorcet and individual Rank Learning Methods" (SIGIR 2009).
- `research/notes/techniquerag.md` (digest of arXiv:2505.11988).
- `analysis/bm25-baseline.md` (measured BM25 profile).
