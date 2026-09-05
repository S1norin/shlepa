---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-dll-hijack-a
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 7
  wall_minutes: 31
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write]
errors:
  minor_count: 1
  minor_classes: [redundant-steps]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "Unsigned image-load of a system-DLL-named file from the app's own directory = DLL search-order hijacking (T1574.001); hedge indicators across raw/decoded verbatim semantics."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-dll-hijack-a
  workspace: tmp/manual-bench-soc-dll-hijack-a
---

# bench-soc-dll-hijack-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3019: `unsigned-image-load` rule fired around 09:00–09:10 UTC
2026-04-22 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings verbatim from evidence;
empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (host WS-IT-18, owner t.nguyen),
  `sysmon.jsonl` (one image-load event: `C:\Program Files\SomeApp\app.exe`
  loads `C:\Program Files\SomeApp\winmm.dll` — a file named after a Windows
  system DLL, placed in the application directory, SHA256
  FE5B44526813446CB02707C831E24F87FE5B44526813446CB02707C831E24F87),
  `background_activity.jsonl` (45 routine entries, pure noise).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
### 2.1 Read instruction, restate goal and contract
- Goal: pin the deliverable shape. Action: read instruction.md.
- Observation: strict 5-key JSON, 3-value taxonomy, verbatim indicators.
- Reasoning: contract-first before evidence.
### 2.2 Inventory evidence
- Goal: see what exists. Action: ls/wc in container.
- Observation: 3 files; sysmon is a single event; background feed 45 lines.
- Reasoning: tiny corpus — full read, no sampling.
### 2.3 Read ticket context
- Goal: get host/owner attribution. Action: `cat ticket_context.txt`.
- Observation: host WS-IT-18, owner t.nguyen, domain corp.local; no engagement record.
- Reasoning: the ticket's asset block is the only source of host/account names (Sysmon carries only the host field).
### 2.4 Read Sysmon event
- Goal: characterize the image load. Action: read the single sysmon event in full.
- Observation: app.exe loads a DLL named `winmm.dll` from its own application directory; the hash marks it as not the genuine system binary.
- Reasoning: a system-DLL-named file shadowing the real one next to the app = DLL search-order hijack signature.
### 2.5 Determine verdict, technique, hosts, accounts
- Goal: fix the five fields. Action: classify.
- Observation: only malicious activity is the hijack image-load on WS-IT-18; only account present in any artifact is host owner t.nguyen.
- Reasoning: TRUE_POSITIVE_INCIDENT; T1574.001 (chose .001 over .002 because the victim app is unmodified and the shadowed name is a system DLL picked up via default search order); hosts=["WS-IT-18"], accounts=["t.nguyen"] (evidence-backed, not invented).
### 2.6 Compose and copy report
- Goal: produce the artifact. Action: 5 indicators (malicious DLL path, loader path, SHA256, bare `winmm.dll`, host); docker cp into container.
- Observation: 380 bytes written.
- Reasoning: paths are backslash-escaped in the JSONL, so full-path indicators are verbatim in decoded values while hash/bare-name/host are verbatim in raw text too — 5 indicators hedge the verbatim check under both interpretations.
### 2.7 Final validation
- Goal: verify every contract requirement. Action: in-container python: key-set equality, enum, raw-substring and decoded-value membership per indicator, types.
- Observation: ALL CHECKS PASS (raw-substring [F,F,T,T,T], decoded-value [T,T,T,T,T]).
- Reasoning: contract-compliant; container left running.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-dll-hijack-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1574.001 / ["WS-IT-18"] / ["t.nguyen"] / 5 indicators (see §2.6).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full evidence (1 Sysmon event + noise feed).
2. Recognize the signature: unsigned image-load of a system-DLL-named file from the app directory ⇒ T1574.001.
3. Attribute from the ticket asset block (WS-IT-18 / t.nguyen) — the only citable host/account.
4. Indicators: DLL path, loader path, hash, bare DLL name, host; validate under both raw-text and decoded-leaf containment; write strict JSON.
### 4.2 Why optimal
One-event task; the only subtleties are the .001/.002 sub-technique choice
(defensible either way, .001 correct here) and verbatim semantics (hedged).
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Over-hedged indicator list  [class: redundant-steps]
- What happened: five indicators were submitted, several overlapping (full DLL path + bare `winmm.dll`; full loader path + host), as deliberate insurance against raw-vs-decoded verbatim semantics.
- Why acceptable: all five were genuine verbatim evidence values; the redundancy costs nothing and protected against an ambiguous containment check.
- Recovery: n/a — validation passed on first submission.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Inventing an account  [class: artifact-contract-violation]
- What it is: reporting a user that appears nowhere in the artifacts.
- Why unacceptable: the only evidence-backed account is the host owner from the ticket.
- How to avoid: attribute strictly from ticket asset block + telemetry subjects.
#### E-C3 Side-loading instead of search-order hijacking  [class: artifact-contract-violation]
- What it is: T1574.002 when the scenario is an unmodified app picking up a system-DLL-named shadow via default search order.
- Why unacceptable: wrong sub-technique string fails the grader.
- How to avoid: check whether the victim app itself has a vulnerable load path (.002) or is simply unmodified (.001).
#### E-C4 Escaped-path indicator  [class: artifact-contract-violation]
- What it is: re-typing Windows paths from raw JSONL so the string value double-escapes.
- Why unacceptable: fails decoded-leaf containment; costs a retry.
- How to avoid: extract paths programmatically or pair each path with a backslash-free twin.

## 6. Agent policy lessons
- "System-DLL name + app directory + unsigned" is the T1574.001 fingerprint; the .001 vs .002 discriminator is whether the victim app has its own load-path weakness (side-loading) or is stock (search-order hijack).
- Pair backslashed path indicators with backslash-free twins (bare file name, hash) so the indicator set survives both raw-text and parsed-leaf containment semantics.
- For single-event tasks, a full read + one classification pass + one validation pass is the whole solution; resist adding tooling.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-dll-hijack-a
docker exec shlepa-manual-bench-soc-dll-hijack-a cat /app/evidence/sysmon.jsonl
docker exec shlepa-manual-bench-soc-dll-hijack-a cat /app/evidence/ticket_context.txt
# write report (5 indicators, 2 path + 3 backslash-free), then:
docker cp tmp/manual-bench-soc-dll-hijack-a/report.json shlepa-manual-bench-soc-dll-hijack-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-dll-hijack-a   # reward=1
reports/tools/taskctl.sh out bench-soc-dll-hijack-a
```
Image: `shlepa-task-bench-soc-dll-hijack-a:env`.
