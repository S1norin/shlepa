# RAG / Retrieval Survey for a Small Structured MITRE KB (issue #89)

- **Category:** rag / knowledge-base (survey for the KB build)
- **Source:** measured sizes in `mitre-formats-sizes.md`, required set in
  `mitre-coverage-audit.md`, papers in `techniquerag.md` + `graphrag.md`
- **Reviewed:** 2026-09-03

Question: how should the agent get MITRE ATT&CK knowledge at task time,
under Shlepa's hard constraints, with the best expected T-ID accuracy per
token?

## Constraints (verified)

| constraint | value |
|---|---|
| ACP runtime | offline, Debian 12, Python 3.12, `rg` preinstalled, **no node, no tree-sitter, no internet, no torch** (`research/code_search/README.md`) |
| Submission zip | ≤ 10 MB (`MAX_ZIP_BYTES`); agent code today ~39 KB |
| Model / budget | ~27B-class local LLM (dev: Qwen3.8:27B), `AGENT_TOKEN_BUDGET` = 300K per task |
| Grading | graders **string-match** `primary_mitre_technique` in `report.json` (e.g. literal `T1562.001`), so ID accuracy is binary per task |
| KB source (pinned) | ATT&CK Enterprise **v19.2** STIX bundle (`6cda5ad8`); 709 live patterns = 233 top-level + 476 sub-techniques |

Measured KB sizes (`mitre-formats-sizes.md`, dev tokenizer):
required-subset field-pruned **6,075 tokens / 24.7 KB**; full matrix
field-pruned **302,133 tokens / 1.19 MB** (too big to hold in-context);
names-only full index **8,571 tokens / 21 KB**; alias (renumber) map
105 entries (~2 KB).

## Options

| # | Option | Zip cost | Per-query prompt tokens | Expected T-ID quality | Effort | Verdict |
|---|---|---|---|---|---|---|
| A1 | No RAG — required subset (14 blocks, id/name/desc/tactics + T1562.001 alias note) as stable prompt prefix | 24.7 KB | 6,075 fixed/turn (prefix-cache amortized) | **Near-perfect on the 8 grader IDs**; zero KB coverage elsewhere → invalid/hallucinated-ID risk (TechniqueRAG error analysis, p. 8) | trivial | fallback |
| A2 | No RAG — **names-only index of the full matrix** (709 `T-ID Name` lines) as stable prefix | 21.1 KB | 8,571 fixed/turn (prefix-cache amortized) | full ID vocabulary → blocks invalid IDs, enables name→ID; no description grounding | trivial | **part of recommendation** |
| B1 | `rg` over the field-pruned KB text (no new tool) | 1.19 MB | ~0.3–0.8K per call (8 raw lines, cap) | lexical, **no ranking** → arbitrary truncation can miss the best match | trivial (file + prompt note) | dominated by B2 |
| B2 | **Read-only `mitre_kb` tool, stdlib-only**: exact-ID lookup + keyword/substring scan + pure-Python BM25 ranking over field-pruned rows, token-capped output | 1.19 MB KB + ~5 KB code | **~1.0–1.5K per call** (top-5 field-pruned rows) | BM25 is the proven baseline for exactly this task (TechniqueRAG: P@1 51.6% alone → 71.3% with LLM re-rank, Table 4 p. 8; the agent loop *is* the re-ranker and can re-query) | small (matches plan build tasks) | **part of recommendation** |
| C | Dense embeddings, offline model in the zip | ≥ 10–25 MB extra (MiniLM-class int8) — **over/edge of budget** | ~1.0–1.5K per call | semantic recall > lexical for paraphrase, but BM25 is already the strong baseline in-domain; no torch in the ACP image → pure-Python inference, slow | large (model + inference path + zip gate) | rejected |
| D | Hybrid BM25 + dense (RRF) | C + B2 | ~1.0–1.5K per call | marginal over B2 in this domain per the evidence above | medium-large | rejected (needs C) |
| E | Graph RAG (Microsoft-style): LLM entity graph + Leiden communities + community summaries + map-reduce query | ~1.2 MB (same KB; graph is the data itself) | **~4.5–5K per query** (map-reduce over 15 tactic summaries) | built for *global* sensemaking, not local factual queries (Edge et al. pp. 1–2, 9); wrong regime | large | rejected as full E |
| E-lite | Hierarchical: **per-tactic dev-time digest** (~1–2K tokens, 15 entries) in the prefix + B2 drill-down | +2–4 KB | ~1–2K prefix + B2 drill-down | tactic-level orientation before querying (GraphRAG's community-summary idea, minus extraction and map-reduce) | small (dev-time script) | optional add-on for the decision |

## Paper review (details in the paper notes)

- **TechniqueRAG** (`techniquerag.md`, arXiv:2505.11988): BM25 (K=40) +
  zero-shot LLM structured-CoT re-rank + LoRA-fine-tuned 8B generator
  constrained to the candidate set. Technique F1 74.02/91.09
  (Tram/Procedures) vs GPT-4o+RAG 62.16/78.82 (Table 2, p. 6).
  Transferable: retrieval + iterative LLM re-ranking over a small
  candidate set, candidate-set-constrained output, parent+sub rows shown
  together, old→new alias handling. Shlepa cannot fine-tune, so the
  generator improvement is unavailable — the agent loop substitutes.
- **GraphRAG** (`graphrag.md`, arXiv:2404.16130): LLM-built entity graph +
  community summaries; map-reduce global search beats vector RAG on
  *global* questions (comprehensiveness 72–83% wins, p. 9) at heavy
  index cost (281 min gpt-4-turbo, p. 9). Our queries are local/factual →
  only the hierarchical-summary idea transfers (E-lite).

## Recommendation (exactly one)

**A2 + B2: the full-matrix names-only index as a stable prompt prefix,
plus a read-only stdlib `mitre_kb` tool (exact-ID / keyword / BM25,
token-capped) over the field-pruned full matrix — including the 105-entry
old→new alias map in the KB data.**

Rationale:

1. **Accuracy path.** Grader IDs are binary string matches. The prefix
   puts the authoritative 709-entry ID↔name vocabulary in-context
   (blocks hallucinated/invalid sub-technique IDs — a measured failure
   mode, TechniqueRAG p. 8), and the tool supplies description-grounded
   candidates on demand. The agent loop plays TechniqueRAG's re-ranker
   role (query → top-K → reason → re-query), with the paper's
   steps→tactics→technique→sub-technique decomposition as the arm prompt
   recipe. The T1562.001 alias requirement is served by the alias map
   (KB answers both IDs; the agent must still echo the grader's old form
   — prompt snippet states this).
2. **Cost path.** Zip ≈ 1.25 MB (≤ 10 MB, ~12× headroom). Per-task:
   8,571-token prefix (2.9% of the 300K budget; near-zero marginal after
   turn 1 *if* prefix/KV caching is active on the serving path —
   **verify in the build phase via the existing `tokens_cache_read`
   telemetry**) plus 1–2 KB tool calls (expect 1–3 per task, ~3K tokens).
   A1+B2 (subset prefix instead of the full index) is the fallback if A/B
   shows the uncached prefix is too expensive; A2's extra 2.5K tokens
   buys the full ID vocabulary, which the invalid-ID failure mode argues
   for.
3. **Rejected.** C/D: no torch in the ACP image and the embedding model
   alone eats the zip budget, for gains BM25 evidence does not justify.
   E: wrong query regime (global sensemaking) and the heaviest
   per-query cost; E-lite (tactic digests) is a cheap optional add-on the
   decision record may adopt.

## Open questions for the decision record

- Prefix scope: full index (A2, recommended) vs required subset (A1) vs
  subset + alias block only — with or without E-lite tactic digests.
- Whether the KB text ships as JSON or plain lines (tool parses either;
  JSON keeps field structure, lines are `rg`-friendly).
- Pinned version policy: v19.2 now; re-generate + re-A/B on major ATT&CK
  releases (IDs/renames drift, as T1562→T1685 shows).
