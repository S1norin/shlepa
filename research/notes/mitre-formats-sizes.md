# MITRE ATT&CK Format & Size Measurement (issue #88)

- **Category:** rag / knowledge-base (measurement for the KB build)
- **Source:** `mitre-attack/attack-stix-data` @ `6cda5ad8` (2026-08-05,
  "feat: add ATT&CK v19.2"), `attack.mitre.org` (Enterprise v19.2 pages)
- **Reviewed:** 2026-09-03
- **Companion note:** `mitre-coverage-audit.md` (required subset, #87)

Question: what do the candidate ATT&CK content formats actually weigh, in
bytes and in tokens of the dev model, and which format should the KB
generator be built from?

## Sources tried

| Source | Result |
|---|---|
| TAXII (`cti-taxii.mitre.org/attackcti`) | **unreachable from this network** (connection failure); GitHub mirror of the same data used instead |
| `attack-navigator` repo static data | not published — the Navigator app fetches from TAXII at runtime; repo has only sample layers. The "Navigator JSON" format is therefore **derived from the STIX bundle** (same field shape) |
| `attack.mitre.org` static exports | none — the site is static Jekyll HTML (matrix page 1.5 MB; per-technique pages 64–292 KB each); no CSV/JSON API |
| `attack-stix-data` repo | **used** — canonical STIX 2.1 bundles per version |

Pinned download: `enterprise-attack/enterprise-attack-19.2.json`
(**53,835,637 bytes**, commit `6cda5ad8462c79e14fbb872f4e09059b18e0cfc4`),
saved as `{scratch}/attack/stix-19.2.json`.

## Bundle contents (v19.2)

- 26,086 STIX objects total: 858 `attack-pattern`
  (709 live / 149 revoked), 21,262 `relationship`, 1,758 `x-mitre-analytic`,
  733 `malware`, 191 `intrusion-set`, 56 `campaign`, 95 `tool`,
  699 `x-mitre-detection-strategy`, 15 `x-mitre-tactic`, …
- Live attack-patterns: **709 = 233 top-level + 476 sub-techniques**;
  12 live-but-deprecated (T1026, T1034, T1043, T1051, T1053.004, T1061,
  T1062, T1064, T1108, T1149, T1153, T1175). The website matrix page
  lists 222 top-level IDs = 233 − 11 deprecated top-level (T1053.004 is a
  deprecated sub-technique), reconciled exactly against
  `matrix_enterprise.html`.
- Object generations are mixed in one bundle: live objects use the
  underscore fields (`x_mitre_is_subtechnique`, `x_mitre_platforms`,
  `kill_chain_phases`), the 149 revoked objects the old dashed fields.
  **Filter: `type == attack-pattern` and not `revoked`.**
- Tactics are 15, with v19.x renames: **Stealth** (TA0005, formerly
  "Defense Evasion"), **Defense Impairment** (TA0112, new). The KB must
  carry current names (the audit note's tactic list comes from the same
  source).
- Sub-technique parent is not a field; derive from the T-ID prefix.
- Renumbered IDs (bundle-confirmed): 105 revoked→live name matches,
  including **`T1562.001 → T1685`** (the one the amsi-bypass graders
  string-match). Full list in `{scratch}/attack/aliases.json`; matches are
  by unique name within the bundle — spot-check before shipping, since a
  split/merge could alias two different techniques.

## Sizes (bytes + dev-model tokens)

Token counts: `scripts/token-count.py` against the dev llama-server
`/tokenize` (Qwen3.8:27B-UD-IQ4_XS), the tokenizer the agent model uses.

| Format | Scope | Bytes | Tokens |
|---|---|---:|---:|
| STIX 2.1 bundle (all objects) | v19.2, 26,086 objects | 53,835,637 | ~13.5M (est., 4 chars/token) |
| STIX bundle, live patterns only | 709 objects | 2,668,711 | 881,881 |
| **Field-pruned JSON** `{id, name, description, tactics, platforms, is_subtechnique, parent, deprecated}` | 709 | **1,190,117** | **302,133** |
| Names-only index `T-ID Name` | 709 | 21,112 | 8,571 |
| Field-pruned, required subset (14 blocks + T1562.001 alias block) | 15 | 24,704 | 6,075 |
| Descriptions-only, required subset (audit) | 14 | 5,975 | 1,351 |
| Website HTML (matrix + per-technique) | 710 pages | ~100M (est.: 5-page sample avg 133 KB × 709 + 1.5 MB matrix) | n/a |

Files: `{scratch}/attack/` — `stix-19.2.json`, `live-techniques-only.json`,
`pruned-all.json`, `names-all.txt`, `aliases.json`,
`pruned-required.json`, `prune_measure.py` (regenerates all from the
bundle; deterministic).

## Findings

1. **The full field-pruned matrix is 1.19 MB / 302K tokens** — far below
   the 10 MB zip budget, but too large to keep in-context every turn
   (302K ≫ a 27B-class model's useful context share). The required subset
   alone is 6K tokens field-pruned / 1,351 tokens descriptions-only.
2. **Smallest format keeping sub-technique granularity:**
   - names-only: 21 KB / 8.6K tokens (IDs + names; no descriptions)
   - field-pruned: 1.19 MB / 302K tokens (adds descriptions, tactics,
     platforms)
   A hierarchical KB (names-only index always available + on-demand
   field-pruned description fetch) costs the **8.6K-token index**
   plus one description per query (~0.5–1.5K tokens) instead of 302K.
3. **Smallest usable base format: field-pruned JSON derived from the
   pinned STIX bundle.** One source, deterministic regeneration, contains
   every field a later compression level needs (drop platforms for a
   leaner variant; names-only is a projection of it). The raw STIX bundle
   is the audit artifact, not a KB input — it is 45× heavier than the
   pruned form and 94% of its objects are not techniques.

## Recommendations (input to the survey/decision notes)

- Build the KB generator on `pruned-all.json` semantics: pinned bundle →
  live patterns → field-pruned rows (+ alias map from `aliases.json`,
  spot-checked).
- Version pin in the KB header: **ATT&CK Enterprise v19.2**, bundle
  commit `6cda5ad8`, bundle SHA-256 recorded at build time.
- Include the 12 deprecated top-level IDs as deprecated rows (the
  graders' expected IDs are all live, but the matrix completeness argues
  for keeping them, flagged `deprecated: true`).
