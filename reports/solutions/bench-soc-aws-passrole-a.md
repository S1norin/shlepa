---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-aws-passrole-a
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
  wall_minutes: 24
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
  key_technique: "PassRole + Lambda bound to an existing privileged role = reuse of a valid cloud credential (T1078.004), not temporary-elevation abuse (T1548.005)."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-aws-passrole-a
  workspace: tmp/manual-bench-soc-aws-passrole-a
---

# bench-soc-aws-passrole-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3023: `cloudtrail-iam-anomaly` (privileged-role manipulation
PassRole + Lambda creation from an external IP) fired around 09:00–09:10 UTC
2026-04-26 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 verbatim strings; empty
technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (Domain corp.local, Host WS-FIN-10, owner
  s.garcia, AWS account 123456789012), `aws_cloudtrail.jsonl` (2 events from
  external IP 45.33.32.156, UA `python-requests/2.28.0`: `PassRole` on
  AdminRole 09:03:27Z; `CreateFunction20150331` for `util-8afc2c04` with role
  `arn:aws:iam::123456789012:role/AdminRole` 09:05:07Z),
  `background_activity.jsonl` (53 routine entries, zero matches for the host/IP/owner).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on technique): full triage correct (verdict/hosts/accounts/
indicators) but technique T1548.005 (Temporary Elevated Cloud Access).
### 2.1 Re-read instruction, inspect rejected report
- Goal: localize the rejection. Action: read instruction; `cat /app/report.json`.
- Observation: only the technique field rejected; 299 bytes, 2-space indent.
- Reasoning: fix exactly one field, keep other bytes identical.
### 2.2 Re-ground the evidence
- Goal: confirm what the telemetry shows. Action: cat ticket + CloudTrail, sample background feed.
- Observation: external IP passes the pre-existing AdminRole, then creates a Lambda bound to its ARN; no userIdentity/host in CloudTrail.
- Reasoning: the actor reused an existing, valid cloud role credential for persistent elevated access — not a sanctioned JIT/temporary-elevation workflow.
### 2.3 MITRE research (logged): T1078.004 vs T1548.005
- Goal: pick the single most defensible sub-technique. Action: fetched both technique pages.
- Observation: T1078.004 = Valid Accounts: Cloud Accounts (using org-created cloud identities); T1548.005 = abusing sanctioned temporary-elevation mechanisms; T1098 = creating/manipulating *new* credentials/roles.
- Reasoning: reuse of an existing role credential ⇒ T1078.004 uniquely; the rejection of T1548.005 confirms the distinction.
### 2.4 One-field fix
- Goal: change only the technique. Action: targeted edit `T1548.005`→`T1078.004` (same length), docker cp back.
- Observation: diff between attempts shows exactly one changed line; 299 bytes both.
- Reasoning: no formatting drift; all other fields byte-identical.
### 2.5 Re-validate full artifact
- Goal: confirm every contract rule. Action: in-container python: key set, enum, non-empty fields, ≥2 indicators, verbatim membership of each indicator in the evidence.
- Observation: all checks passed — 5 indicators (`45.33.32.156`, the role ARN, `util-8afc2c04`, `python-requests/2.28.0`, `PassRole`) verbatim in CloudTrail/ticket.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-aws-passrole-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1078.004 / ["WS-FIN-10"] / ["s.garcia"] / 5 indicators (see §2.5).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full CloudTrail (2 events) + scan the routine feed for host/IP/owner matches (none).
2. Classify: external IP, scripted UA, PassRole then Lambda bound to a pre-existing privileged role ⇒ reuse of a valid cloud credential ⇒ T1078.004; not T1548.005 (no sanctioned JIT workflow) and not T1098 (no *new* credentials created/manipulated).
3. Attribute WS-FIN-10 / s.garcia from the ticket asset block (CloudTrail carries no host/userId).
4. Indicators: source IP, role ARN, Lambda function name, UserAgent, `PassRole`; strict JSON; one validation pass.
### 4.2 Why optimal
Two-event task; the single real decision is the cloud-account sub-technique,
which the "pre-existing role, reused" fact settles (a 30-second MITRE
lookup is the cost).
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Temporary-elevation sub-technique  [class: near-miss-logic]
- What happened: attempt 1 mapped PassRole+Lambda to T1548.005 (Temporary Elevated Cloud Access).
- Why acceptable: both sub-techniques involve cloud roles; the distinction (sanctioned JIT mechanism vs. reuse of an existing credential) is subtle and was resolved with a logged MITRE lookup.
- Recovery: T1078.004; single-field fix with byte-identical diff and full re-validation; reward=1.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Inventing host/account  [class: artifact-contract-violation]
- What it is: deriving a compromised host/user from CloudTrail, which contains none; or picking a user not in the ticket.
- Why unacceptable: only the ticket asset block names WS-FIN-10 / s.garcia.
- How to avoid: attribute from the ticket asset block, cite the provenance.
#### E-C3 New-credentials sub-technique  [class: artifact-contract-violation]
- What it is: T1098.001/T1098.003 (creating/manipulating new credentials) when no new credential is created.
- Why unacceptable: the evidence shows *reuse* of a pre-existing role, so the T1098 family is wrong.
- How to avoid: check whether the compromised credential existed before the actor's actions.
#### E-C4 Ticket-label indicator  [class: artifact-contract-violation]
- What it is: using `cloudtrail-iam-anomaly` (ticket-only text) as an indicator.
- Why unacceptable: fails verbatim evidence containment.
- How to avoid: indicators only from CloudTrail/ticket evidence values.

## 6. Agent policy lessons
- Cloud-role triage ladder: existing credential reused ⇒ T1078.004; sanctioned temp-elevation workflow abused ⇒ T1548.005; new credentials/roles created/manipulated ⇒ T1098.001/.003; umbrella T1626 only when no sub-technique fits. The "pre-existing, then bound" ordering in CloudTrail is the decisive fact.
- Same-length field edits (`T1548.005`→`T1078.004`) keep byte diffs minimal — diff the two versions to prove only the intended field changed.
- Scripted UserAgents (e.g. `python-requests/…`) + external IP are strong external-actor markers even without userIdentity fields.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-aws-passrole-a
docker exec shlepa-manual-bench-soc-aws-passrole-a cat /app/evidence/aws_cloudtrail.jsonl
# fix: T1078.004; 5 verbatim indicators (IP, ARN, function, UA, PassRole)
docker cp tmp/manual-bench-soc-aws-passrole-a/report.json shlepa-manual-bench-soc-aws-passrole-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-aws-passrole-a   # reward=1
reports/tools/taskctl.sh out bench-soc-aws-passrole-a
```
Image: `shlepa-task-bench-soc-aws-passrole-a:env`.
