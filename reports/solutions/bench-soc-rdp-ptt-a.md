---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-rdp-ptt-a
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
  wall_minutes: 6
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
  key_technique: "LogonType-10 interactive logon onto a sensitive server from a workstation = RDP lateral movement (T1021.001); indicators only from parsed JSONL string leaves."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-rdp-ptt-a
  workspace: tmp/manual-bench-soc-rdp-ptt-a
---

# bench-soc-rdp-ptt-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3016: `rdp-lateral-anomaly` fired around 09:00–09:10 UTC
2026-04-19 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict` (3-value taxonomy), `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings verbatim from evidence).
### 1.2 Environment facts
- Evidence: `ticket_context.txt`, `windows_event_logs.jsonl` (6 events; the
  signal is one 4624 LogonType 10 — 09:05:14Z, FS-FINANCE-02, user k.brown,
  WorkstationName WS-IT-07, IpAddress 10.10.7.100, Kerberos),
  `zeek_conn.jsonl` (one RDP TCP flow 10.10.2.50→10.10.4.124:3389,
  09:05:07Z, ~713 s, SF), `background_activity.jsonl` (39 routine entries).
- Note: `event_id`/`dst_port` are JSON integers, not string leaves.
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on one indicator): read ticket, correlated the single
LogonType-10 4624 with the 3389 flow, classified TRUE_POSITIVE_INCIDENT /
T1021.001 / FS-FINANCE-02 / k.brown; indicators included the ticket label
`rdp-lateral-anomaly` (ticket-only text) → rejected by verifier.
### 2.1 Re-read instruction, inspect rejected report
- Goal: localize the rejection. Action: cat report + instruction.
- Observation: verdict/technique/hosts/accounts all matched; `rdp-lateral-anomaly` failed verbatim; `LogonType 10` is a field-name+value paraphrase that would also fail.
- Reasoning: only `key_indicators` needs rebuilding; keep the four matched fields untouched.
### 2.2 Inspect evidence and event schema
- Goal: know which strings exist as values. Action: full read of all three JSONL + ticket.
- Observation: the 4624 fields (k.brown, 10, WS-IT-07, 10.10.7.100, Kerberos), the RDP flow endpoints (10.10.2.50, 10.10.4.124); ints are not string leaves.
- Reasoning: candidate verbatim set = the distinctive string leaves around the logon + flow.
### 2.3 Run verbatim leaf-check on candidates
- Goal: machine-prove each candidate. Action: `check_indicators.py` — json-parse every line, collect string leaves, assert substring membership.
- Observation: OK: k.brown, 10.10.7.100, FS-FINANCE-02, WS-IT-07, 10.10.2.50, 10.10.4.124, Kerberos. FAIL: `rdp-lateral-anomaly`, `LogonType 10`, `4624` (int).
- Reasoning: confirms both failures; picks six distinctive verbatim indicators, drops the weak bare `"10"`.
### 2.4 Rewrite report, re-validate full artifact
- Goal: persist fix. Action: new 6-item `key_indicators`, matched fields unchanged; docker cp; validator asserts key set, enum, types, ≥2 distinct, per-indicator leaf-substring.
- Observation: all PASS; 315 bytes.
- Reasoning: artifact now fully contract-compliant.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-rdp-ptt-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1021.001 / ["FS-FINANCE-02"] / ["k.brown"] / indicators `[k.brown, FS-FINANCE-02, 10.10.7.100, WS-IT-07, 10.10.2.50, 10.10.4.124]`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + all evidence (small).
2. Isolate the single LogonType-10 4624 (interactive) onto FS-FINANCE-02 by k.brown from WS-IT-07/10.10.7.100; corroborate with the 3389 flow seconds earlier.
3. Classify: interactive RDP logon to a sensitive server from a workstation = lateral movement ⇒ T1021.001, TRUE_POSITIVE_INCIDENT; no engagement record excludes FP-pentest.
4. Build indicators exclusively from parsed JSONL string leaves (account, host, source IP, workstation, flow IPs) and validate each by leaf-substring check before writing.
### 4.2 Why optimal
One decisive event + one corroborating flow; the indicator rule (JSONL string
leaves only) is the single failure source in this family and is eliminated
upfront.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Ticket-label indicator  [class: near-miss-logic]
- What happened: attempt 1 used `rdp-lateral-anomaly` (the rule name) and a `LogonType 10` paraphrase as indicators; the rule name exists only in `ticket_context.txt`, and the paraphrase is not a stored value.
- Why acceptable: all analytical fields were correct; the fix was mechanical (rebuild the indicator list from string leaves) and completed in one retry.
- Recovery: leaf-substring check program; final six indicators all verbatim in JSONL leaves.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Attributing the source workstation  [class: artifact-contract-violation]
- What it is: listing WS-IT-07 (origin) as a compromised host.
- Why unacceptable: no malicious activity is evidenced on the origin; hosts = execution hosts.
- How to avoid: keep hosts to the target of the lateral logon.
#### E-C3 Wrong verdict on sensitive-target lateral RDP  [class: artifact-contract-violation]
- What it is: downgrading to BENIGN_ANOMALY because the Zeek flow IPs differ from the 4624 client IP.
- Why unacceptable: an interactive logon onto a finance server from a workstation is the incident; telemetry granularity does not negate it.
- How to avoid: weigh the logon event's semantics over imperfect IP correlation.
#### E-C4 Non-verbatim indicators  [class: artifact-contract-violation]
- What it is: indicators not present as evidence values (labels, paraphrases, ints-as-strings).
- Why unacceptable: explicit contract clause.
- How to avoid: validate every indicator against parsed JSONL string leaves before writing.

## 6. Agent policy lessons
- Indicators must be *values stored in the telemetry* (parsed string leaves). Ticket/rule labels live only in the ticket text and fail verbatim checks; event-id integers are not string leaves.
- For lateral-movement tickets, the execution host is the logon target; the origin workstation is context, not a compromised host.
- When a verifier rejects one field, re-validate the *whole* artifact (key set, types, all indicators) in the same session — cheap insurance against a second failure mode.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-rdp-ptt-a
docker exec shlepa-manual-bench-soc-rdp-ptt-a cat /app/evidence/windows_event_logs.jsonl
docker exec shlepa-manual-bench-soc-rdp-ptt-a cat /app/evidence/zeek_conn.jsonl
# write report (6 JSONL-leaf indicators), then:
docker cp tmp/manual-bench-soc-rdp-ptt-a/report.json shlepa-manual-bench-soc-rdp-ptt-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-rdp-ptt-a   # reward=1
reports/tools/taskctl.sh out bench-soc-rdp-ptt-a
```
Image: `shlepa-task-bench-soc-rdp-ptt-a:env`.
