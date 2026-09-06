---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-ntds-vss-b
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 22
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write]
errors:
  minor_count: 0
  minor_classes: []
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "VSS shadow copy + FILE_READ_DATA on shadow NTDS.dit = T1003.003; backslash-free verbatim indicators chosen upfront."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-ntds-vss-b
  workspace: tmp/manual-bench-soc-ntds-vss-b
---

# bench-soc-ntds-vss-b

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3052: `dc-process-anomaly` fired on DC01 around 09:00–09:10 UTC
2026-04-19 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 verbatim strings; empty
technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (corp.local, DC01.corp.local),
  `windows_event_logs.jsonl` (5 events: 4688 `vssadmin create shadow /for=C:`
  by l.martin on DC01 09:02:09Z; 4663 access to the shadow NTDS.dit with
  AccessList `%%4416` (FILE_READ_DATA) by l.martin 09:04:13Z; 3 routine
  LogonType-2 logons for a.patel/s.garcia/p.adams on workstations),
  `background_activity.jsonl` (27 routine entries, none on DC01).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
### 2.1 Read instruction, restate contract
- Goal: pin deliverable shape. Action: read instruction.md.
- Observation: strict 5-key JSON, 3-value taxonomy, verbatim indicators, empty fields for non-incidents.
- Reasoning: contract-first.
### 2.2 Inventory evidence
- Goal: see what exists. Action: ls/cat/wc on evidence dir.
- Observation: 3 files, tiny (5 events, 27 background entries).
- Reasoning: full read is complete and cheap.
### 2.3 Read all evidence
- Goal: correlate. Action: printed both JSONL files in full.
- Observation: l.martin on DC01: vssadmin shadow create (09:02:09) → FILE_READ_DATA on shadow NTDS.dit (09:04:13); the rest is routine logons/background noise.
- Reasoning: canonical NTDS dump via VSS; no engagement context anywhere.
### 2.4 Determine verdict
- Goal: choose among the 3 taxonomy values. Action: checked all artifacts for authorization context.
- Observation: no pentest/engagement markers; l.martin not an authorized tester; no benign purpose for reading NTDS.dit.
- Reasoning: not FP-pentest, not benign ⇒ TRUE_POSITIVE_INCIDENT.
### 2.5 Select fields, write report
- Goal: produce the artifact. Action: verdict TP, T1003.003, hosts ["DC01"], accounts ["l.martin"], indicators `["vssadmin create shadow /for=C:", "NTDS.dit", "%%4416"]` (command line, target file, access mask); docker cp to /app/report.json.
- Observation: 251 bytes written.
- Reasoning: deliberately avoided the escaped shadow path; all three strings are verbatim under any parsing interpretation.
### 2.6 Validate artifact
- Goal: re-check every requirement. Action: in-container python: key-set equality, taxonomy, ≥2 indicators, raw-substring presence of every indicator/host/account.
- Observation: VALIDATION OK.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-ntds-vss-b` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact as listed in §2.5.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full evidence.
2. Correlate 4688 vssadmin + 4663 shadow NTDS.dit FILE_READ_DATA by the same account on DC01 ⇒ T1003.003, TRUE_POSITIVE_INCIDENT.
3. Pick backslash-free verbatim indicators (command line, `NTDS.dit`, `%%4416`).
4. Write strict JSON via a library; single validation pass.
### 4.2 Why optimal
Two-event fingerprint; the `%%4416` access mask adds a third independent
verbatim datum without escaping risk. Nothing else is needed.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
(none)
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Attributing to a workstation account  [class: artifact-contract-violation]
- What it is: reporting a.patel/s.garcia/p.adams (routine logons) as compromised accounts.
- Why unacceptable: only the subject of the malicious chain is attributable.
- How to avoid: attribute from the DC01 event chain only.
#### E-C3 Wrong or base technique ID  [class: artifact-contract-violation]
- What it is: T1003 without .003, or a non-credential-dumping technique.
- Why unacceptable: grader requires the NTDS sub-technique.
- How to avoid: shadow NTDS.dit ⇒ T1003.003 exactly.
#### E-C4 Escaped-path indicator  [class: artifact-contract-violation]
- What it is: copying the raw `\\Device\\…` text so the string value double-escapes and fails verbatim matching.
- Why unacceptable: violates the verbatim clause and costs a retry.
- How to avoid: backslash-free substrings or programmatically extracted parsed leaves.

## 6. Agent policy lessons
- Access masks (`%%4416` = FILE_READ_DATA) are strong, short, escaping-free indicators that also prove read access — prefer them over long paths when available.
- The absence of any engagement record plus a credential-store read makes the incident verdict near-deterministic; do not hedge with BENIGN_ANOMALY.
- Keep the write path simple: host-side JSON + `docker cp` + in-container validator; the file is 250 bytes, no build system needed.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-ntds-vss-b
docker exec shlepa-manual-bench-soc-ntds-vss-b cat /app/evidence/windows_event_logs.jsonl
# write report (5 keys; indicators: command line, NTDS.dit, %%4416), then:
docker cp tmp/manual-bench-soc-ntds-vss-b/report.json shlepa-manual-bench-soc-ntds-vss-b:/app/report.json
reports/tools/taskctl.sh verify bench-soc-ntds-vss-b   # reward=1
reports/tools/taskctl.sh out bench-soc-ntds-vss-b
```
Image: `shlepa-task-bench-soc-ntds-vss-b:env`.
