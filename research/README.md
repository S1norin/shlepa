# Research

How research is done in this repo and where artifacts live. Read this before
adding anything under `research/`.

## Layout

```
research/
├── README.md          # this file: conventions
├── notes/             # one digest per paper/idea: <slug>.md
├── papers/            # PDF registry: <slug>.pdf + registry table
├── benchmarks/        # benchmark research (self-contained)
│   ├── README.md      # master index: one row per benchmark
│   ├── notes/         # one digest per benchmark/paper: <slug>.md
│   ├── papers/        # benchmark PDFs: <slug>.pdf + registry table
│   └── analysis/      # cross-cutting analysis docs
└── code_search/       # code-search tooling research (self-contained)
    ├── README.md      # context, hard constraints, master index, decision record
    ├── notes/         # one digest per tool: <slug>.md
    └── analysis/      # cross-cutting analysis (fit matrix)
```

- `notes/` + `papers/` (top level) are for **agent-architecture and general
  LLM research** — how to build the agent (models, fine-tuning, loops,
  tool use).
- `benchmarks/` is for **evaluation research** — external benchmarks and
  papers that measure security/agent capability. Everything benchmark-related
  (notes, PDFs, analysis) stays inside `benchmarks/`.
- `code_search/` is for **code-search tooling research** — search/index
  engines and retrieval techniques the agent can use to find code with less
  context. Self-contained like `benchmarks/` (own README index, notes,
  analysis).

## Rules

1. **English only** in every file (same as the rest of the repo).
2. **One file per subject**: a note is a digest of exactly one benchmark,
   paper, or idea. Cross-links between notes are fine; don't merge subjects.
3. **Slugs**: lowercase hyphenated, matching the subject's common name
   (`deepred.md`, `agentdojo.md`). PDFs use the same slug as their note
   (`papers/deepred.pdf` ↔ `notes/deepred.md`).
4. **Registry discipline**: every PDF stored under a `papers/` directory gets
   a row in that directory's `README.md` table (slug, title, link, why).
   Every benchmark gets a row in `benchmarks/README.md`.
5. **Cite primary sources**. Each note ends with a `Sources` section: paper
   (arXiv/DOI), code repo, dataset. If a claim could not be verified against a
   primary source, mark it `unverified` explicitly instead of dropping it.
6. **Freshness**: notes carry a `Reviewed: YYYY-MM-DD` date in the header.
   Re-verify before relying on a note older than ~6 months (benchmarks move
   fast).
7. **Small commits**, Conventional Commits: `docs(research): add <slug> note`,
   `docs(research): download <slug> paper`. One logical change per commit.

## Note template

Use this structure for benchmark notes (`benchmarks/notes/`); keep it compact
(≤ ~150 lines):

```markdown
# <Name>

- **Category:** ctf | vuln-exploit | soc | agent-security | knowledge | general | infra
- **Source:** org / venue, year
- **Paper:** <arXiv/DOI link> (PDF: `papers/<slug>.pdf`)
- **Code:** <github link> · **Data:** <HF/dataset link>
- **Reviewed:** YYYY-MM-DD

## What it tests
## Environment        # runtime, isolation, resources, internet?
## Tasks              # count, categories, 1–3 concrete examples
## Scoring            # metrics, partial credit, judge (executable vs LLM)
## Fit for Shlepa     # overlap with contest task families, offline feasibility,
                       # adaptation cost to a Harbor task, recommendation
## Sources
```

Paper digests in top-level `notes/` follow the existing digest shape
(motivation, method, gains, applicability to Shlepa, benchmarks).

## From research to work

- A benchmark worth adapting into a dev task → adapt it per
  [`docs/tasks.md`](../docs/tasks.md) using the `<bench>-` slug prefix and
  `[metadata]` provenance keys. The note's "Fit for Shlepa" section is the
  decision record.
- Promising ideas (techniques, model choices) → GitHub issues via the
  `backlog` / `github-issues` pi skills. Don't keep a backlog in this file.
- Large artifacts (task material > a few MB) do **not** go into the repo;
  record URLs in the note instead. PDFs are the only binary artifact stored
  here.

## Tooling

- Web: the `web-search` skill (local SearXNG). Batch related queries, keep
  `--limit 3`, fetch known URLs directly.
- PDFs: download arXiv/PDFs with `curl -L -o`; verify with `file`.
  Extract text for digests with the `pdf-reading` / `liteparse` skill.
