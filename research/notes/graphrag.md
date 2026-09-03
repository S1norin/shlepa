# GraphRAG (Edge et al., 2024)

- **Paper:** "From Local to Global: A Graph RAG Approach to
  Query-Focused Summarization" (arXiv:2404.16130) —
  `research/papers/2024-edge-graphrag.pdf`
- **Category:** rag / retrieval architecture (review for issue #89)
- **Reviewed:** 2026-09-03

Question: does a graph-based RAG (knowledge graph + community summaries +
map-reduce) beat vector RAG, and for which *kind* of query is it worth
the index cost?

## Method

- Index (LLM-built, dev-time): extract an entity knowledge graph from the
  corpus, partition with Leiden community detection, then generate
  **community summaries bottom-up** (each level summarizes its
  sub-communities) (p. 1).
- Query: two modes. *Local search* = ego-network retrieval around
  matched entities (vector-RAG-like). *Global search* = **map-reduce over
  all community summaries** — each summary answers the query partially,
  partials are reduced into the final answer (p. 1).
- Evaluation: adaptive benchmarking — an LLM generates global
  sensemaking questions from persona use-cases; a second LLM judges
  answers (no ground truth exists for global questions) (§2.3, p. 3).

## Results

- On ~1M-token corpora (podcast transcripts, news articles), the global
  approach significantly beats conventional vector RAG (SS) on
  comprehensiveness (win rates 72–83%) and diversity (75–82%) for global
  questions; **vector RAG gives the most *direct* answers**
  (§5.1, p. 9).
- Indexing cost is large: 281 minutes of gpt-4-turbo calls for one
  dataset at a 600-token graph-indexing window (§4.1.3, p. 9).
- The headline result is scoped to **global sensemaking** ("what are the
  main themes?"); the paper is explicit that vector RAG "works well for
  queries that can be answered with information localized within a small
  set of records" (pp. 1–2).

## Applicability to Shlepa

- Shlepa's MITRE queries are **local and factual** ("which T-ID matches
  this evidence?"), not corpus-global sensemaking — the regime where
  GraphRAG's map-reduce adds cost (extra LLM passes per query) without
  the benefit it was built for.
- The transferable idea is the **hierarchical pre-computed summaries**:
  the ATT&CK taxonomy is already a small explicit graph (15 tactics →
  233 techniques → 476 sub-techniques, v19.2). Dev-time LLM digests per
  tactic (community summaries, trivially cheap at 302K tokens of source)
  give a compact always-on "map of the territory" prefix with
  drill-down to exact rows — the GraphRAG summary hierarchy minus the
  entity-graph extraction and map-reduce runtime.
- The dev-time LLM index cost concern does not apply to Shlepa: the KB
  source is structured (no entity extraction needed) and summarization
  runs once, on the strong dev model.

## Benchmarks

Podcast transcripts (~1M tokens) and news articles (2013–2023);
LLM-as-judge with 5 criteria (comprehensiveness, diversity,
empowerment, directness, faithfulness); graph sizes 8.5K/15.8K nodes
(§5.1, p. 9).
