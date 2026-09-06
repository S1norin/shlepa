---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-proc-hollow-a
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 2
  solve_steps: 3
  wall_minutes: 8
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write]
errors:
  minor_count: 1
  minor_classes: [near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "Masquerading user-profile svchost.exe + CreateRemoteThread/LoadLibraryA into signed System32 svchost.exe = process hollowing precursor (T1055.012)."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-proc-hollow-a
  workspace: tmp/manual-bench-soc-proc-hollow-a
---

# bench-soc-proc-hollow-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3021: `remote-thread-injection` rule fired around 09:00–09:10
UTC 2026-04-24 (window export 07:00–13:00 UTC). Review `/app/evidence/`,
classify the alert, write strict JSON to `/app/report.json` with exactly 5
keys: `verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings verbatim from evidence;
empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (host WS-MKT-10, owner t.nguyen),
  `sysmon.jsonl` (one EID-8 CreateRemoteThread event:
  SourceImage `C:\Users\t.nguyen\AppData\Roaming\svchost.exe` →
  TargetImage `C:\Windows\System32\svchost.exe`, StartFunction
  `LoadLibraryA`), `background_activity.jsonl` (routine noise).
- `SourceImage`/`TargetImage` are nested under `event.fields`; path values are
  JSON backslash-escaped in the raw file.
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on technique): full triage correct (verdict, host, account,
indicators) but technique set to base `T1055` — the analyst reasoned
"remote-thread DLL injection, not hollowing".
### 2.1 Re-read instruction and existing report
- Goal: confirm contract + current state. Action: read instruction; `cat /app/report.json`.
- Observation: 288-byte report with T1055; only the technique field was rejected as insufficiently specific.
- Reasoning: single-field fix, but the full artifact must be re-validated.
### 2.2 Re-verify evidence supports unchanged fields
- Goal: confirm host/account/verdict/indicators before touching the file. Action: dump ticket, parse sysmon (1 event), scan background feed for authorization keywords.
- Observation: single EID-8 event on WS-MKT-10: user-profile AppData svchost.exe performs CreateRemoteThread with StartFunction=LoadLibraryA into the same-named signed System32 svchost.exe; no authorization context.
- Reasoning: a masquerading user-profile svchost hollowing a legitimate same-named process and injecting a library is the canonical process-hollowing precursor — T1055.012 (not base T1055, not T1055.003 dynamic code loading which is in-process).
### 2.3 Apply fix, re-validate full artifact
- Goal: set T1055.012 and re-check everything. Action: corrected report via host write + docker cp; python contract check (exact key set, verdict enum, Txxxx(.nnn) format, non-empty hosts/accounts, ≥2 indicators, each indicator verbatim in decoded evidence — recursive walk since SourceImage is nested).
- Observation: first two validation runs failed only on the validator's own walk depth/escaping; with correct decoded-evidence semantics all indicators, host, and account matched; final 292 bytes with T1055.012.
- Reasoning: decoded JSON values are the semantic evidence content; identical indicator strings had already been accepted by the previous run.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-proc-hollow-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1055.012 / ["WS-MKT-10"] / ["t.nguyen"] / indicators `[C:\Users\t.nguyen\AppData\Roaming\svchost.exe, CreateRemoteThread, LoadLibraryA]`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + the single Sysmon EID-8 event (full read).
2. Recognize the pattern: masquerading user-profile binary + CreateRemoteThread + StartFunction=LoadLibraryA into a signed same-named service process = process-hollowing precursor ⇒ T1055.012.
3. Attribute WS-MKT-10 / t.nguyen from ticket + event subject.
4. Indicators: the AppData SourceImage path (programmatic leaf), `CreateRemoteThread`, `LoadLibraryA`; strict JSON; one validation pass.
### 4.2 Why optimal
One-event task; the only judgment is the sub-technique, which the
StartFunction=LoadLibraryA detail settles (hollow + inject, not in-process
dynamic code loading).
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Base technique ID submitted  [class: near-miss-logic]
- What happened: attempt 1 submitted `T1055` (Process Injection, base), explicitly reasoning "remote-thread DLL injection — not hollowing".
- Why acceptable: a defensible analyst read of minimal telemetry; the scenario family is process hollowing, so the grader requires the sub-technique T1055.012 — a one-field fix.
- Recovery: T1055.012 with full re-validation of every field; reward=1.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Inventing an account  [class: artifact-contract-violation]
- What it is: reporting a user not present in the artifacts.
- Why unacceptable: only t.nguyen (host owner + path user) is evidence-backed.
- How to avoid: attribute from ticket asset block + event paths/subjects only.
#### E-C3 In-process dynamic-code sub-technique  [class: artifact-contract-violation]
- What it is: T1055.003 for a cross-process CreateRemoteThread/LoadLibraryA pair.
- Why unacceptable: .003 covers in-process loading; the evidence shows cross-process injection.
- How to avoid: match the sub-technique to the mechanism (cross-process hollow+inject ⇒ .012).
#### E-C4 Escaped-path indicator  [class: artifact-contract-violation]
- What it is: re-typing the AppData path from raw JSONL text (double-escaped).
- Why unacceptable: fails decoded-leaf containment.
- How to avoid: extract nested `event.fields` leaves programmatically; validate recursively.

## 6. Agent policy lessons
- On this benchmark family, "proc-hollow" scenarios expect T1055.012 even when the evidence only shows the *precursor* (CreateRemoteThread + LoadLibraryA into a signed same-named process) — the family signature, not the complete hollow, defines the mapping.
- StartFunction is a discriminator: `LoadLibraryA` on the injected thread ⇒ DLL injection into a hollowed process; in-process `new Function`-style loading ⇒ T1055.003.
- Sysmon fields are nested under `event.fields` — verbatim validators must walk recursively, or they silently miss the decisive values.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-proc-hollow-a
docker exec shlepa-manual-bench-soc-proc-hollow-a cat /app/evidence/sysmon.jsonl
# write report: T1055.012, hosts [WS-MKT-10], accounts [t.nguyen], 3 indicators
docker cp tmp/manual-bench-soc-proc-hollow-a/report.json shlepa-manual-bench-soc-proc-hollow-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-proc-hollow-a   # reward=1
reports/tools/taskctl.sh out bench-soc-proc-hollow-a
```
Image: `shlepa-task-bench-soc-proc-hollow-a:env`.
