# MITRE ATT&CK Technique Coverage Audit (Forensics Preset)

- **Category:** rag / knowledge-base (audit for issue #87)
- **Source:** graders under `tasks/bench-soc-*/tests/`,
  `attack.mitre.org` (Enterprise v19.2), dev llama-server tokenizer
- **Reviewed:** 2026-09-03

Question: which MITRE ATT&CK technique IDs do the forensics-preset tasks
actually grade, how do those IDs map to the current ATT&CK matrix, and how
big is the required subset in tokens?

## Method

- `REQUIRED_MITRE` extracted from every `tasks/bench-soc-*/tests/report_grader.py`.
- Each ID resolved against the live matrix at `attack.mitre.org`
  (Enterprise **v19.2** per the site resources page, 2026-09-03).
- Technique pages fetched (meta-refresh redirects followed, which is how
  renumbered IDs are exposed) and field-pruned to id / name / description /
  tactics; token count via `scripts/token-count.py` (dev llama-server
  `/tokenize`, Qwen3.8:27B-UD-IQ4_XS).
- Raw data: `{scratch}/attack/` (`matrix_counts.json`,
  `required_subset_techniques.json`, `required_subset_kb.txt`).

## Required set per task (grader ground truth)

| Task(s) | Grader expects | Current v19.2 ID | Technique name |
|---|---|---|---|
| bench-soc-ntds-vss, -a, -b | `T1003.003` | T1003.003 | OS Credential Dumping: NTDS |
| bench-soc-rdp-ptt-a, -b | `T1021.001` | T1021.001 | Remote Services: Remote Desktop Protocol |
| bench-soc-proc-hollow-a, -b | `T1055.012` | T1055.012 | Process Injection: Process Hollowing |
| bench-soc-https-beacon-a, -b | `T1071.001` | T1071.001 | Application Layer Protocol: Web Protocols |
| bench-soc-dns-tunnel-a, -b | `T1071.004` | T1071.004 | Application Layer Protocol: DNS |
| bench-soc-aws-passrole-a, -b | `T1098.003` | T1098.003 | Account Manipulation: Additional Cloud Roles |
| bench-soc-amsi-bypass-a, -b | `T1562.001` | **T1685** (parent) | Disable or Modify Tools |
| bench-soc-dll-hijack-a, -b | `T1574.001` | T1574.001 | Hijack Execution Flow: DLL Side-Loading |
| bench-soc-scanner-fp | (none — `verdict=FALSE_POSITIVE_AUTHORIZED_PENTEST`) | — | — |
| contest-incident-log-forensics | (none — four key=value fields, no T-ID) | — | — |
| bench-ctf-whyos | (none — flag-based CTF) | — | — |

Unique required: **8 sub-technique IDs / 7 top-level techniques**
(T1003, T1021, T1055, T1071, T1098, T1574, T1685) spanning **8 tactics**
(current v19.2 names: Command and Control, Credential Access, Defense
Impairment, Execution, Lateral Movement, Persistence, Privilege Escalation,
Stealth).

## Key finding: T1562.001 is a renumbered ID

`attack.mitre.org/techniques/T1562/001/` and `/techniques/T1562/` both
meta-refresh to **T1685 "Disable or Modify Tools"** in v19.2 (its current
sub-techniques are T1685.001–.006, e.g. `.001 Disable or Modify Windows
Event Log`). The amsi-bypass graders still expect the literal string
`T1562.001`, so:

1. The KB must carry an **old→new alias map** (T1562.001 → T1685) — the
   current matrix alone cannot answer the task.
2. The agent's `report.json` must echo the **grader's ID** (old form), not
   the current one. The KB entry for T1685 should list both IDs.

## Sizes

| Scope | Items | Chars | Tokens (dev tokenizer) |
|---|---|---|---|
| Required subset, field-pruned (14 blocks: 8 sub-techs + 6 parents, id/name/desc/tactics) | 14 | 5,975 | **1,351** |
| Full v19.2 matrix (website matrix page, top-level IDs only) | 222 techniques, 14 tactics | — | measured in formats-sizes |

Tactics were also renamed in v19.x (the enterprise tactics page now lists
e.g. **Stealth** and **Defense Impairment** where older docs say "Defense
Evasion"). The KB should carry current tactic names with a note for the
familiar ones.

The required subset is tiny — it fits in a small-LLM context with room to
spare. The KB's value is therefore in **descriptions + tactic context +
alias mapping**, not in retrieving from a large corpus. Full-matrix sizes
(STIX bundle / Navigator JSON / markdown, with sub-technique count) are
measured in the formats-sizes task.

## What not to do

- Do not emit the current ID (T1685.x) in `report.json` for the amsi tasks —
  the grader string-matches `T1562.001`.
- Do not rely on the TAXII server (`cti-taxii.mitre.org`) — it is
  unreachable from this dev network (connect timeout), and the ACP
  container is offline anyway. Use static artifacts.

## Sources

- https://attack.mitre.org/resources/ (v19.2)
- https://attack.mitre.org/techniques/enterprise/ (matrix, 222 top-level)
- https://attack.mitre.org/techniques/T1685/ (renumbered technique)
- `tasks/bench-soc-*/tests/report_grader.py` (REQUIRED_MITRE strings)
