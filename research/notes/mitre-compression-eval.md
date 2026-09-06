# MITRE ATT&CK Compression Evaluation (issue #90)

- **Category:** rag / knowledge-base (evaluation for issue #90)
- **Source:** `mitre-attack/attack-stix-data` @ `6cda5ad8` (enterprise
  v19.2 bundle, pinned), dev llama-server (Qwen3.8:27B-UD-IQ4_XS:
  tokenizer for all counts, thinking-off for distillation),
  `tasks/bench-soc-*/tests/report_grader.py`
- **Reviewed:** 2026-09-03
- **Companion notes:** `mitre-coverage-audit.md` (#87),
  `mitre-formats-sizes.md` (#88), `mitre-rag-survey.md` (#89)

Question: what are the token budgets of the candidate compression levels,
and what does each level actually lose, measured against what the
SOCBench graders require?

## Levels measured

- **(a) Field-pruned** — `{id, name, description, tactics, platforms,
  is_subtechnique, parent, deprecated}` rows from the pinned STIX bundle
  (`prune_measure.py`, deterministic).
- **(b) LLM-distilled cheat sheet** — each technique compressed to 1-3
  lines (max 400 chars, `|`-joined) by the dev model, generated at dev
  time from (a) content (`distill_cheats.py`: batches of 5, temperature
  0.2, thinking off, strict-JSON with truncation salvage, retry with
  missing-only re-prompt). The committed artifact is one JSONL row per
  technique `{"id", "name", "cheat"}`. **Not deterministic per run** —
  one generated artifact is pinned and re-runs must diff-check. The
  full-matrix artifact was generated 2026-09-03: 709/709 rows, 0
  failed batches, id/name verified against the source rows.
- **(c) Hierarchical** — names-only index (`T-ID Name`, all 709) as a
  stable prefix + on-demand retrieval of full (a) rows (the survey's
  A2+B2 recommendation).
- **(c') Hierarchical with (b)** — same index prefix, but on-demand
  retrieval returns (b) cheat rows instead of (a) rows.

## The required subset is larger than the audit says

The audit (#87) extracted one ID per task. The graders actually accept
**several** IDs per task (`REQUIRED_MITRE` lists):

| Task | Grader accepts (verbatim) |
|---|---|
| ntds-vss | `T1003.003` |
| rdp-ptt | `T1021.001`, `T1550.003` |
| proc-hollow | `T1055.012` |
| https-beacon | `T1071.001`, `T1573.002` |
| dns-tunnel | `T1071.004` |
| aws-passrole | `T1098.003`, `T1078.004` |
| amsi-bypass | `T1562.001` |
| dll-hijack | `T1574.001` |

**Finding:** three grader-acceptable IDs are missing from the audit's
15-block required subset: **T1078.004 (Cloud Accounts), T1550.003
(Pass the Ticket), T1573.002 (Asymmetric Cryptography)**. The
**extended required set** = 11 sub-technique IDs (10 live + the
T1562.001→T1685 alias block) + 10 parents = **21 blocks**.

v19.2 renumbering also changed two of the secondary IDs' *names*:
T1550.003 is "Pass the Ticket" and T1573.002 is "Asymmetric
Cryptography" in v19.2 (the slot previously held "VPN"). Both semantics
fit their scenarios, and the grader string-matches the IDs, so the
extended set is safe to build from live v19.2 rows.

## Token budgets (dev tokenizer, exact)

| Level | Full matrix (709) | Audit required (15) | Extended required (21) |
|---|---:|---:|---:|
| (a) field-pruned JSON | 1,190,117 B / **302,133 tok** | 24,704 B / 6,075 tok | 35,488 B / **8,701 tok** |
| (b) cheat sheet JSONL | **54,665 tok** (207,562 B, 709 rows) | 1,157 tok | **1,361 tok** (18 rows) |
| (c) names-only index | 21,112 B / **8,571 tok** | 164 tok | **230 tok** |
| (c)/(c') on-demand, top-5 rows | ~2,130 tok / ~380 tok per call | — | — |
| (c') on-demand, top-5 cheat rows | ~380 tok per call | — | — |
| descriptions-only (all) | **217,451 tok** (per-technique p50 281 / p95 599 / max 1,042) | 1,351 tok | 5,930 tok |
| old→new alias map (105 entries) | 2,006 tok (needed in every scope) | 2,006 tok | 2,006 tok |

Per-row on-demand cost: (a) ≈ 426 tok average (302,133 / 709), (b) ≈
77 tok average (54,665 / 709; 76 on the required subset). The (b) row
is the unit (c') retrieves.

The extended set's 18 (b) rows cover all 11 grader-accepted
sub-techniques; its 3 parent rows beyond the audit set (T1078, T1550,
T1573) exist only in the (a)/(c) forms (parents serve as naming
context, not grader targets).

Zip budget check: (a)+(c) ≈ 1.21 MB; (b) full ≈ 203 KB. All far under
10 MB; the binding constraint is context, not zip.

## What the graders actually need from MITRE knowledge

Grader contract (identical shape in every `bench-soc-*/tests/report_grader.py`);

- `verdict` — exact string
- `primary_mitre_technique` — must **contain** one of the accepted IDs
  (case-insensitive substring)
- `compromised_hosts` / `compromised_accounts` — exact after normalization
- `key_indicators` — ≥2 strings, each verbatim in the evidence, covering
  ≥2 IOC keywords

**Only `primary_mitre_technique` depends on MITRE knowledge.** The rest
is evidence-derived. So the KB's job is narrow: map observed artifacts
(e.g. `0x1410`, `ntds.dit`, `passrole`) to the right T-ID string.

### Per-task mapping strength by level

Evidence anchors are the grader IOC keywords. "Name-only" = what level
(c)'s index provides alone (ID + name + alias).

| Task | Evidence anchor | Accepted ID(s) | (c) index alone | (a) row | (b) cheat |
|---|---|---|---|---|---|
| amsi-bypass | amsi, 0x1410, powershell | T1562.001→T1685 | **weak** — name "Disable or Modify Tools" is generic | grounded — description: "security tools (EDR, IDS, AV, logging agents, sensors)" | grounded — tool-stop/kill indicators; **no AMSI string** |
| ntds-vss | ntds.dit, vssadmin | T1003.003 | strong ("NTDS") | strong | strong (cheat cites `Ntds.dit`, `vssadmin`, secretsdump) |
| rdp-ptt | TCP 3389 | T1021.001 / T1550.003 | strong ("Remote Desktop Protocol") | strong | strong (cheat: "TCP 3389") |
| proc-hollow | svchost, CreateRemoteThread | T1055.012 | strong ("Process Hollowing") | strong | strong (cheat: CREATE_SUSPENDED + injection call chain) |
| https-beacon | HTTPS beacon :443 | T1071.001 / T1573.002 | moderate ("Web Protocols") | strong | strong (cheat: high-volume low-payload HTTPS) |
| dns-tunnel | DNS TXT to cdn-* | T1071.004 | strong ("DNS") | strong | strong (cheat: DNS TXT/A beaconing) |
| aws-passrole | passrole, adminrole | T1098.003 / T1078.004 | strong ("Additional Cloud Roles") | strong | strong (cheat: IAM policy update APIs, O365 roles) |
| dll-hijack | winmm.dll, dwmapi.dll | T1574.001 | **weak** — v19.2 name is just "DLL" | strong (description: side-loading, search order) | strong (cheat: sideloading, search-order hijack) |

The index alone is weak on **2 of 8** (amsi-bypass, dll-hijack); both
are resolved by description or cheat content. This is the argument for
retrieval-with-content, not index-only.

### AMSI case study (worst case)

"AMSI" and "0x1410" occur **nowhere in any live v19.2 technique
object** — checked descriptions, procedures, examples, and detection
fields of all 709 patterns. No compression level can string-match the
evidence to the ID; the mapping must be inferential: "PowerShell AMSI
bypass = disabling a security tool ⇒ which technique covers impairing
defensive tooling?" Level (a) and (b) both answer it via the scope
definition; level (c) alone does not.

### Field importance for T-ID mapping

Ranked by what the 8 tasks need:

1. **Sub-technique name** — usually the direct semantic anchor
   ("NTDS", "Process Hollowing", "Remote Desktop Protocol").
2. **Description** — the scope definition; resolves the two weak cases
   above and disambiguates siblings under one parent (T1071.001 vs
   .004).
3. **Alias map** — mandatory: without T1562.001→T1685 the amsi task is
   unanswerable in v19.2.
4. **Tactics** — sibling-disambiguation aid (defense-impairment vs
   execution); cheap, keep.
5. **Platforms** — relevance filter (all current tasks are
   Windows/AWS-centric); cheap, keep.
6. **Examples / procedures / detection guidance** — **not present in
   v19.2 STIX objects at all** (field census: no live pattern carries
   `x_mitre_procedures`/`x_mitre_examples`/`x_mitre_detection`), so no
   level can keep them from the pinned bundle. Concrete indicator
   strings (tools, paths, API names) are therefore only re-derivable by
   LLM distillation (level b), and only from the description.
7. References / external links / contributors — zero mapping value;
   already dropped by (a).

### Level-(b) quality caveats

- **Fidelity check passed** on the 18 generated rows: `id`/`name` match
  the source rows exactly; line/char limits hold. Spot-check of two
  suspicious details: "ElGamal" in the T1573.002 cheat is verbatim in
  the source description (grounded); the T1078.004 cheat cites T1098.001
  as a cross-reference — interpretive, not verbatim source text
  (harmless, but shows cheats add paraphrase).
- **Observed risk:** cheats generalize. The T1685/T1562.001 cheat
  lists generic tool-impairment indicators and drops any AMSI
  specificity (none exists in the source; a query for "amsi" must map
  via the scope definition, not string match).
- **Process requirement:** the artifact must be pinned; regeneration
  must diff-check (LLM output is not reproducible); id/name equality
  against the source rows must be asserted by the build script.

## What this means for the decision

- **Required-only scope, level (b):** 1,361 tok (18 rows) covers every
  grader-acceptable ID of the forensics preset, fully in-context, no
  retrieval code needed. Cheapest complete design for the current
  forensics preset; zero headroom for tasks outside it.
- **Full-matrix scope:** level (c) prefix (8,571 tok) blocks invalid
  IDs everywhere. On-demand content then decides the per-query cost:
  (c)+(a) ≈ 2.1K tok per top-5 call; **(c')+(b) ≈ 380 tok per top-5
  call** — 5-6× cheaper, at the fidelity cost above. The survey
  recommendation (A2+B2 over field-pruned rows) stays valid; this note
  offers (b) as a cheaper on-demand corpus and (a) as the
  higher-fidelity fallback (the tool can serve both, keyed per row).
- Any scope needs the 2,006-tok alias map (grader string-matches old
  IDs).

## Artifacts & reproduction

All in `{scratch}/attack/`: `prune_measure.py` (a), `distill_cheats.py`
(b), `measure_levels.py` (c + extended set + description distribution),
`scripts/token-count.py` (counts); data: `pruned-all.json`,
`pruned-required.json`, `req-ext-*.json|txt`, `cheat-all.jsonl`,
`cheat-req-ext.jsonl`, `aliases.json`. Pinned source:
`enterprise-attack-19.2.json` (53,835,637 B, commit `6cda5ad8`).

## Sources

- `tasks/bench-soc-*/tests/report_grader.py` (grader contract, REQUIRED_MITRE lists)
- `enterprise-attack-19.2.json` (mitre-attack/attack-stix-data @ `6cda5ad8`)
- https://attack.mitre.org/resources/ (v19.2)
- Companion notes above (#87-#89)
