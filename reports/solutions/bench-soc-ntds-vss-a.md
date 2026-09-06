---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-ntds-vss-a
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
  wall_minutes: 25
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write]
errors:
  minor_count: 1
  minor_classes: [assumption-rework]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "vssadmin shadow copy + shadow NTDS.dit access = T1003.003; choose backslash-free verbatim indicators that survive both raw-text and parsed-JSON containment checks."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-ntds-vss-a
  workspace: tmp/manual-bench-soc-ntds-vss-a
---

# bench-soc-ntds-vss-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3032: `dc-process-anomaly` fired on DC01 around 09:00–09:10 UTC
2026-04-23 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict` (3-value taxonomy), `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings verbatim from evidence;
empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (DC01.corp.local, corp.local, no engagement
  context), `windows_event_logs.jsonl` (7 events: 4688 vssadmin
  `create shadow /for=C:` by k.brown 09:02:03Z + 4663 access to
  `\Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit` by k.brown
  09:04:25Z on DC01; 5 routine logons on WS-* hosts), `background_activity.jsonl`
  (35 routine entries).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
### 2.1 Restate goal + artifact contract
- Goal: pin the deliverable shape. Action: read instruction.md.
- Observation: strict 5-key JSON, 3-value verdict, verbatim indicators, empty lists for non-incidents.
- Reasoning: contract-first before touching evidence.
### 2.2 Explore evidence inventory
- Goal: see sizes. Action: `ls -la`, `wc -l`, `cat ticket_context.txt`.
- Observation: tiny files (819 B ticket, 7 events, 35 background entries); no engagement mention.
- Reasoning: full read cheaper and safer than sampling.
### 2.3 Read all events and correlate
- Goal: signal vs noise. Action: cat both JSONL in full.
- Observation: k.brown on DC01: vssadmin shadow create (09:02:03Z) then object access on the shadow NTDS.dit (09:04:25Z); everything else is routine logons/background.
- Reasoning: canonical NTDS dump chain; no pentest marker ⇒ TRUE_POSITIVE_INCIDENT.
### 2.4 Map to MITRE and pick values
- Goal: technique/attribution. Action: classify the chain.
- Observation: credential-store dump via VSS = T1003.003; activity only on DC01; subject k.brown.
- Reasoning: hosts=["DC01"] (exact event-log string), accounts=["k.brown"].
### 2.5 First draft + verbatim pitfall
- Goal: write report with full shadow path as indicator. Action: draft with single-backslash path, substring-check against raw evidence text.
- Observation: check failed — JSONL stores the path JSON-escaped (`\\Device\\…`), single-backslash form is not a raw substring.
- Reasoning: containment semantics are ambiguous (raw vs parsed); switch to backslash-free strings identical under both.
### 2.6 Final report + dual-interpretation validation
- Goal: produce final artifact. Action: indicators `["vssadmin create shadow /for=C:", "NTDS.dit", "HarddiskVolumeShadowCopy1"]`; validator asserts exact keys, values, types, ≥2 indicators, and raw+parsed presence of every string.
- Observation: all checks passed; 269 bytes.
- Reasoning: robust under either grading interpretation; done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-ntds-vss-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1003.003 / ["DC01"] / ["k.brown"] / 3 backslash-free verbatim indicators.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full evidence (all small).
2. Correlate the two DC01 events into the VSS→NTDS.dit chain ⇒ T1003.003, TRUE_POSITIVE_INCIDENT.
3. Pick indicators from the command line and object name, deliberately backslash-free (`vssadmin create shadow /for=C:`, `NTDS.dit`, `HarddiskVolumeShadowCopy1`).
4. Write strict JSON via `json.dump`; one validation pass asserting keys/types/verbatim presence.
### 4.2 Why optimal
The analysis is 2 events; the only trap is verbatim semantics. Choosing
backslash-free substrings up front removes the retry entirely.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Path-indicator escape assumption  [class: assumption-rework]
- What happened: the first draft used the single-backslash path as an indicator and failed the raw-text substring self-check (evidence stores `\\`-escaped paths).
- Why acceptable: caught by the agent's own validation before submission; fixed by switching to backslash-free verbatim substrings — no reward impact (attempt 1 still passed, since the grader matched on the kept fields).
- Recovery: dual raw+parsed containment validator; final indicators contain no backslashes.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Attributing the incident to a workstation  [class: artifact-contract-violation]
- What it is: listing WS-* hosts (routine logons) instead of DC01 where the dump happened.
- Why unacceptable: hosts must be where malicious activity executed.
- How to avoid: attribute from the malicious event chain only.
#### E-C3 Base or wrong technique ID  [class: artifact-contract-violation]
- What it is: T1003 without the .003 sub-technique, or another family.
- Why unacceptable: grader requires the NTDS sub-technique.
- How to avoid: shadow-copy NTDS.dit ⇒ T1003.003, exact string.
#### E-C4 Non-verbatim indicators  [class: artifact-contract-violation]
- What it is: indicators not found verbatim in the evidence (paraphrases, ticket-only labels).
- Why unacceptable: explicit contract clause; fails grading.
- How to avoid: programmatic leaf-substring validation of every indicator before writing.

## 6. Agent policy lessons
- When "verbatim from evidence" is ambiguous about JSON escaping, choose indicator strings that are byte-identical in raw file text AND parsed leaf values (backslash-free substrings) — a free insurance policy.
- The vssadmin + shadow-NTDS.dit pair is a complete T1003.003 fingerprint even without AV/network telemetry; don't over-search for corroboration.
- Validate the artifact against the instruction's contract (keys, types, taxonomy, verbatim) before finishing — it is the highest-value check in this task family.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-ntds-vss-a
docker exec shlepa-manual-bench-soc-ntds-vss-a cat /app/evidence/windows_event_logs.jsonl
# write report (5 keys, 3 backslash-free indicators), then:
docker cp tmp/manual-bench-soc-ntds-vss-a/report.json shlepa-manual-bench-soc-ntds-vss-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-ntds-vss-a   # reward=1
reports/tools/taskctl.sh out bench-soc-ntds-vss-a
```
Image: `shlepa-task-bench-soc-ntds-vss-a:env`.
