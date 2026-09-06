---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-amsi-bypass-a
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
  wall_minutes: 15
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
  key_technique: "Reflection-based amsiInitFailed=true script block + correlated process-access on amsi.dll = T1562.001 (Impair Defenses: Disable or Modify Tools)."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-amsi-bypass-a
  workspace: tmp/manual-bench-soc-amsi-bypass-a
---

# bench-soc-amsi-bypass-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3022: `powershell-scriptblock-anomaly` rule fired around
09:00–09:10 UTC 2026-04-25 (window export 07:00–13:00 UTC). Review
`/app/evidence/`, classify the alert, write strict JSON to `/app/report.json`
with exactly 5 keys: `verdict`, `primary_mitre_technique`,
`compromised_hosts`, `compromised_accounts`, `key_indicators` (≥2 strings
verbatim from evidence; empty technique/hosts/accounts unless
TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (host WS-HR-20, owner t.nguyen),
  `windows_event_logs.jsonl` (one EID-4104 script-block event on WS-HR-20
  09:01:17Z with the canonical AMSI bypass one-liner
  `[Ref].Assembly.GetType('System.Management.Automation.AmsiUtils').GetField('amsiInitFailed','NonPublic,Static').SetValue($null,$true)`;
  8 routine logon events on *other* hosts — decoys), `sysmon.jsonl` (one
  EID-10 process-access: powershell.exe → `C:\Windows\System32\amsi.dll`,
  GrantedAccess `0x1410`, 09:01:50Z), `background_activity.jsonl` (routine).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
### 2.1 Read ticket + inventory evidence
- Goal: restate contract, see what's on disk. Action: read instruction.md; `ls /app/evidence`.
- Observation: 4 artifacts, all small; contract = strict 5-key JSON with verbatim indicators.
- Reasoning: full read feasible.
### 2.2 Full dump of all evidence
- Goal: correlate, separate signal from decoys. Action: `docker exec cat` all files.
- Observation: exactly one 4104 (WS-HR-20, AMSI one-liner) and one Sysmon EID-10 (powershell.exe touching amsi.dll, 33 s later); all logons are on other hosts; background is routine.
- Reasoning: the correlated pair lands inside the alert window on the alerted host — exactly the ticket's described pattern.
### 2.3 Verdict + MITRE mapping
- Goal: choose the single most important technique. Action: reason over the evidence.
- Observation: no scanner signatures, no external IPs/domains, no engagement context; the act is deliberate disabling of an endpoint defense.
- Reasoning: TRUE_POSITIVE_INCIDENT; T1562.001 (Impair Defenses: Disable or Modify Tools) — PowerShell execution (T1059.001) is the vehicle, not the salient behavior.
### 2.4 Host/account attribution
- Goal: populate hosts/accounts from evidence only. Action: grouped logons by host.
- Observation: no logon event exists for WS-HR-20; the only account associated with it in the artifacts is host owner t.nguyen (ticket).
- Reasoning: hosts=["WS-HR-20"], accounts=["t.nguyen"] — cited from the ticket artifact, not invented; other logon users are decoys.
### 2.5 Key-indicator selection
- Goal: ≥2 indicators robust to however containment is checked. Action: chose backslash-free forms.
- Observation: AMSI one-liner (ScriptBlockText), `amsi.dll`, `powershell.exe`, `0x1410`.
- Reasoning: each is a substring of both raw JSONL text and parsed values (paths are double-backslash in raw, single in parsed) — robust under either semantics.
### 2.6 Write + validate
- Goal: produce and verify the artifact. Action: write report, docker cp, validator asserting exact keys, taxonomy, types, count, per-indicator raw+parsed containment, host/account evidence.
- Observation: all indicators raw=True parsed_substring=True; ALL CHECKS PASSED; 379 bytes, exactly 5 keys.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-amsi-bypass-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1562.001 / ["WS-HR-20"] / ["t.nguyen"] / 4 indicators (see §2.5).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full evidence (tiny).
2. Recognize the canonical AMSI-bypass one-liner in the 4104 + the correlated amsi.dll process-access ⇒ deliberate defense impairment.
3. Map to T1562.001 (disable/modify security tools); attribute WS-HR-20 / t.nguyen from the ticket asset block.
4. Indicators: the one-liner + backslash-free tails (`amsi.dll`, `powershell.exe`, `0x1410`); strict JSON; one validation pass.
### 4.2 Why optimal
The payload string is a known-bad fingerprint; the correlated Sysmon event
confirms it executed against AMSI; nothing else is needed.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
(none)
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Attributing a decoy logon user  [class: artifact-contract-violation]
- What it is: reporting one of the 8 logon users (all on other hosts) as the compromised account.
- Why unacceptable: no malicious activity is tied to those users; only the ticket ties t.nguyen to WS-HR-20.
- How to avoid: attribute from the alerted host's evidence + ticket asset block only.
#### E-C3 PowerShell-execution technique instead of defense impairment  [class: artifact-contract-violation]
- What it is: T1059.001 (execution) instead of T1562.001 (the salient behavior).
- Why unacceptable: the grader expects the impairment technique for this family.
- How to avoid: when the payload's purpose is disabling a control, report the Disable-or-Modify-Tools sub-technique.
#### E-C4 Escaped-path indicator  [class: artifact-contract-violation]
- What it is: full `C:\Windows\System32\amsi.dll` re-typed from raw text.
- Why unacceptable: backslash escaping makes raw/decoded containment diverge.
- How to avoid: backslash-free tails or programmatically extracted leaves.

## 6. Agent policy lessons
- The AMSI reflection one-liner is a memorized known-bad string — its presence in a 4104 is a fingerprint, no deep analysis needed; spend the effort on attribution and the correct technique (impairment, not execution).
- Decoy logons on other hosts are a deliberate distractor in this family; group by host before attributing accounts.
- When telemetry lacks a user field for the alerted host, the ticket's host-owner field is the legitimate evidence-backed attribution source (cite it, don't invent).

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-amsi-bypass-a
docker exec shlepa-manual-bench-soc-amsi-bypass-a cat /app/evidence/windows_event_logs.jsonl
docker exec shlepa-manual-bench-soc-amsi-bypass-a cat /app/evidence/sysmon.jsonl
# write report (one-liner + 3 backslash-free indicators), then:
docker cp tmp/manual-bench-soc-amsi-bypass-a/report.json shlepa-manual-bench-soc-amsi-bypass-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-amsi-bypass-a   # reward=1
reports/tools/taskctl.sh out bench-soc-amsi-bypass-a
```
Image: `shlepa-task-bench-soc-amsi-bypass-a:env`.
