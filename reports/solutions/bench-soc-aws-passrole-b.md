---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-aws-passrole-b
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 2
  solve_steps: 5
  wall_minutes: 11
  verifier: tests/test.sh
  network_research: true
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write, web-fetch]
errors:
  minor_count: 1
  minor_classes: [near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "External IP reuses the pre-existing AdminRole (PassRole → Lambda) = Valid Accounts: Cloud Accounts (T1078.004), not the umbrella T1626."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-aws-passrole-b
  workspace: tmp/manual-bench-soc-aws-passrole-b
---

# bench-soc-aws-passrole-b

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3043: `cloudtrail-iam-anomaly` (privileged-role manipulation
PassRole + Lambda creation from an external IP) fired around 09:00–09:10 UTC
2026-04-22 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 verbatim strings; empty
technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (Host WS-ENG-04, owner r.chen, AWS account
  123456789012), `aws_cloudtrail.jsonl` (2 events from external IP
  91.108.4.22, UA `python-requests/2.28.0`: `PassRole` on AdminRole
  09:03:28Z; `CreateFunction20150331` for `util-dc83e7a3` bound to
  `arn:aws:iam::123456789012:role/AdminRole` 09:05:30Z),
  `background_activity.jsonl` (51 routine entries).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on technique): everything correct except the umbrella
technique T1626 (Privilege Escalation: Cloud).
### 2.1 Re-read instruction and existing report
- Goal: confirm contract + current state. Action: read instruction; `cat /app/report.json` (350 bytes).
- Observation: only the technique field rejected.
- Reasoning: one-field fix, all else byte-identical.
### 2.2 Re-ground the evidence
- Goal: verify the classification basis. Action: cat ticket + CloudTrail, scan background feed.
- Observation: external IP passes the pre-existing AdminRole then creates Lambda `util-dc83e7a3` bound to its ARN; no host/userId in CloudTrail; background 100% routine.
- Reasoning: reuse of an existing privileged role credential by an external scripted actor.
### 2.3 MITRE research (logged): T1078.004
- Goal: settle the specific sub-technique. Action: fetched T1078.004.
- Observation: T1078.004 = reuse of org-created cloud identities; the page distinguishes it from T1098.001 (creation of new credentials) and T1548.005 (sanctioned temporary elevation).
- Reasoning: the AdminRole pre-existed and was reused ⇒ T1078.004 is the correct granularity; the umbrella T1626 was rejected for lack of specificity.
### 2.4 One-field fix
- Goal: set T1078.004. Action: python JSON round-trip in container (read → set → dump indent=2 + newline).
- Observation: 350 bytes, exactly one field changed.
- Reasoning: round-trip keeps formatting stable.
### 2.5 Re-validate full artifact
- Goal: verify contract. Action: key-set equality, enum, non-empty fields, ≥2 indicators, verbatim membership of all 6 indicators in evidence.
- Observation: all pass — indicators: `91.108.4.22`, `PassRole`, `CreateFunction20150331`, `util-dc83e7a3`, the role ARN, `python-requests/2.28.0`.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-aws-passrole-b` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1078.004 / ["WS-ENG-04"] / ["r.chen"] / 6 indicators (see §2.5).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full CloudTrail (2 events) + scan background feed (routine).
2. Classify: external scripted IP reuses a pre-existing privileged role (PassRole → Lambda bound to its ARN) ⇒ T1078.004; reject umbrella T1626 (non-specific), T1548.005 (no sanctioned JIT), T1098 (no new credentials).
3. Attribute WS-ENG-04 / r.chen from the ticket asset block.
4. Indicators: source IP, `PassRole`, `CreateFunction20150331`, function name, role ARN, UserAgent; strict JSON; one validation pass.
### 4.2 Why optimal
Identical two-event shape to the -a instance; the sub-technique decision is
the single real one and is settled by the "pre-existing role, reused" fact.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Umbrella technique instead of sub-technique  [class: near-miss-logic]
- What happened: attempt 1 submitted T1626 (Privilege Escalation: Cloud) — correct family, insufficient specificity.
- Why acceptable: the family mapping was right; the grader requires the specific sub-technique, resolved with a logged MITRE lookup (T1078.004 page, incl. its contrast with T1098.001 and T1548.005).
- Recovery: one-field fix to T1078.004, JSON round-trip kept formatting stable, full re-validation; reward=1.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Inventing host/account  [class: artifact-contract-violation]
- What it is: deriving host/user from CloudTrail (which carries none) or naming a user absent from the ticket.
- Why unacceptable: only the ticket asset block names WS-ENG-04 / r.chen.
- How to avoid: attribute from the ticket asset block with provenance noted.
#### E-C3 Wrong cloud sub-technique family  [class: artifact-contract-violation]
- What it is: T1098.001/.003 (new credentials) or T1548.005 (temporary elevation) for reuse of an existing role.
- Why unacceptable: the decisive fact — the AdminRole pre-existed and was reused — excludes both.
- How to avoid: first establish whether the credential is pre-existing (→T1078.004) or created/manipulated by the actor (→T1098).
#### E-C4 Ticket-label indicator  [class: artifact-contract-violation]
- What it is: using `cloudtrail-iam-anomaly` as an indicator.
- Why unacceptable: ticket-only text; fails verbatim evidence containment.
- How to avoid: indicators only from CloudTrail/ticket evidence values.

## 6. Agent policy lessons
- For AWS-role scenarios, determine credential provenance before mapping: pre-existing & reused ⇒ T1078.004; created/manipulated ⇒ T1098.001/.003; sanctioned JIT abused ⇒ T1548.005; umbrella T1626 only as a last resort.
- EventName values (`PassRole`, `CreateFunction20150331`) are clean verbatim indicators — prefer API/event names and identifiers over prose.
- Reuse the family mapping across -a/-b instances; re-verify only per-instance facts (IP, ARN, function, host, account).

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-aws-passrole-b
docker exec shlepa-manual-bench-soc-aws-passrole-b cat /app/evidence/aws_cloudtrail.jsonl
# fix: T1078.004; 6 verbatim indicators (IP, event names, function, ARN, UA)
docker cp tmp/manual-bench-soc-aws-passrole-b/report.json shlepa-manual-bench-soc-aws-passrole-b:/app/report.json
reports/tools/taskctl.sh verify bench-soc-aws-passrole-b   # reward=1
reports/tools/taskctl.sh out bench-soc-aws-passrole-b
```
Image: `shlepa-task-bench-soc-aws-passrole-b:env`.
