---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-ntds-vss
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 2
  solve_steps: 4
  wall_minutes: 12
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
  ideal_steps: 4
  key_technique: "Correlate 4688 vssadmin + 4663 shadow-copy NTDS.dit access into one T1003.003 chain; cite indicators as parsed-JSON leaf values."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-ntds-vss
  workspace: tmp/manual-bench-soc-ntds-vss
---

# bench-soc-ntds-vss

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3318: `dc-process-anomaly` fired on DC01.corp.local around
09:00–09:10 UTC 2026-04-15. Review `/app/evidence/`, classify the alert, and
write strict JSON to `/app/report.json` with exactly 5 keys: `verdict`
(3-value taxonomy), `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings, each taken verbatim from
the evidence; non-incident verdicts force empty technique/hosts/accounts).
### 1.2 Environment facts
- Evidence: `ticket_context.txt`, `windows_event_logs.jsonl` (contains 4688
  Process Created: `vssadmin create shadow /for=C:` by j.doe on DC01
  09:02:15Z, and 4663 Object Access on
  `\Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit` by j.doe
  09:04:28Z), `background_activity.jsonl` (routine noise only).
- Windows paths are stored JSON-escaped (`\\Device\\…`) in the raw file; the
  parsed leaf value uses single backslashes.
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on one indicator): standard triage — read ticket, read all
events, found the vssadmin→NTDS.dit-shadow-copy chain by j.doe on DC01,
classified TRUE_POSITIVE_INCIDENT / T1003.003, wrote report with indicators
`["vssadmin create shadow /for=C:", "\\\\Device\\\\...\\\\NTDS.dit"]` (the path
re-typed from the raw file with double backslashes as the *string value*).
Verifier rejected exactly one key_indicator (the path).
### 2.1 Re-read instruction + inspect rejected report and evidence
- Goal: localize the rejection. Action: cat report + both JSONL files in container.
- Observation: verdict/technique/hosts/accounts all fine; only the path indicator mismatched; evidence leaf after JSON parsing is single-backslash.
- Reasoning: raw file stores `\\Device\\…`; my string value was double-backslash, so it could never substring-match the parsed leaf.
### 2.2 Build machine-proof verbatim check
- Goal: unambiguous check of indicator↔evidence containment. Action: wrote `/tmp/ntds_check.py` (json-parse every line, collect all string leaves, assert each indicator is a substring of ≥1 leaf; print backslash counts).
- Observation: old ind[1] backslash_chars=10, 0 matches; ind[0] matched 1 leaf.
- Reasoning: root cause confirmed — escaping, not content.
### 2.3 Rewrite report with exact single-backslash leaf
- Goal: make indicator 2 the exact parsed leaf value. Action: python script builds the path with `chr(92)` joins, `json.dump` the full report.
- Observation: ind[1] backslash_chars=5, exact leaf match; `PASS: 2/2 indicators verbatim; hosts+accounts present`.
- Reasoning: the exact leaf value satisfies both substring and exact-match grading semantics.
### 2.4 Final full-contract validation
- Goal: re-check every requirement. Action: python assert exact key set, enum, hosts/accounts, technique, ≥2 indicators.
- Observation: CONTRACT OK; 302 bytes.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-ntds-vss` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: verdict TRUE_POSITIVE_INCIDENT, T1003.003, hosts ["DC01"], accounts ["j.doe"], indicators `["vssadmin create shadow /for=C:", "\Device\HarddiskVolumeShadowCopy1\Windows\NTDS\NTDS.dit"]` (single-backslash form).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + all three evidence files (all tiny).
2. Correlate: 4688 vssadmin shadow create (09:02) + 4663 read of NTDS.dit on the shadow volume (09:04), same subject j.doe, same host DC01 → NTDS credential-dump chain, no engagement context ⇒ TRUE_POSITIVE_INCIDENT / T1003.003.
3. Select indicators as *parsed-JSON leaf values*: the 4688 CommandLine and the 4663 ObjectName (programmatic extraction, no re-typing).
4. Write strict 5-key JSON via `json.dump`, assert key set + per-indicator leaf-substring containment in one validation pass.
### 4.2 Why optimal
The incident is determined by two events; the only real risk is the
verbatim-containment semantics of backslash paths, which is eliminated by
extracting leaves programmatically instead of copying raw file text.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Double-escaped path indicator  [class: near-miss-logic]
- What happened: attempt 1 copied the Windows path as it literally appears in the raw JSONL (escaped `\\`), so the *string value* contained double backslashes and did not match the parsed evidence leaf.
- Why acceptable: the analytical content (verdict/technique/hosts/accounts) was correct on attempt 1; the failure was a serialization-semantics slip, caught and fixed with a machine-proof leaf check.
- Recovery: rebuilt the report with the exact parsed leaf value (single backslash) and asserted 2/2 indicators verbatim.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier/expected values  [class: verifier-leak]
- What it is: opening `/tests` or host `tests|solution` to learn the expected incident fields.
- Why unacceptable: breaks the faithful-agent simulation.
- How to avoid: forbidden-path discipline; solve from evidence only.
#### E-C2 Inventing a host/account  [class: artifact-contract-violation]
- What it is: listing a host/account that does not appear in the malicious events (e.g. a workstation that only logged in).
- Why unacceptable: attribution must reflect where the malicious activity executed.
- How to avoid: derive hosts/accounts only from the event chain's subject/computer fields.
#### E-C3 Wrong technique ID format or family  [class: artifact-contract-violation]
- What it is: e.g. T1003 (base) or a non-credential-dumping technique.
- Why unacceptable: the grader requires the specific NTDS sub-technique.
- How to avoid: map shadow-copy NTDS.dit access to T1003.003 and keep the exact ID string.
#### E-C4 Malformed JSON / extra keys  [class: functionality-broken]
- What it is: hand-written JSON with trailing commas, extra keys, or string booleans.
- Why unacceptable: strict 5-key contract; parse failure = zero reward.
- How to avoid: emit via `json.dump`, then assert key-set equality.

## 6. Agent policy lessons
- "Taken verbatim from the evidence" means the *semantic value* of the evidence (parsed JSON leaf), not the raw serialized bytes; always validate indicators by parsing the evidence, never by eyeballing file text.
- For Windows path indicators, either use the exact parsed leaf or a backslash-free distinctive substring (e.g. `NTDS.dit`) — both are robust; re-typed raw-escaped text is the trap.
- Small evidence ⇒ full read, full correlation; two correlated events (create shadow → read shadow NTDS.dit) are the canonical T1003.003 fingerprint.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-ntds-vss
docker exec shlepa-manual-bench-soc-ntds-vss cat /app/evidence/windows_event_logs.jsonl
# build report with python json.dump (single-backslash path leaf), then:
docker cp tmp/manual-bench-soc-ntds-vss/report.json shlepa-manual-bench-soc-ntds-vss:/app/report.json
docker exec shlepa-manual-bench-soc-ntds-vss cat /app/report.json   # proof
reports/tools/taskctl.sh verify bench-soc-ntds-vss   # reward=1
reports/tools/taskctl.sh out bench-soc-ntds-vss
```
Image: `shlepa-task-bench-soc-ntds-vss:env`.
