---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-dns-tunnel-a
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 5
  wall_minutes: 3
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
  key_technique: "Sustained high-entropy TXT query/answer exchange with one external domain = DNS tunnel C2 (T1071.004)."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-dns-tunnel-a
  workspace: tmp/manual-bench-soc-dns-tunnel-a
---

# bench-soc-dns-tunnel-a

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3026 (opened 2026-04-17 09:15 UTC): `dns-entropy-volume` rule
flagged sustained TXT query volume with long high-entropy labels toward an
external domain during the window (source endpoint per the asset inventory).
Review `/app/evidence/`, classify the alert, write strict JSON to
`/app/report.json` with exactly 5 keys: `verdict`, `primary_mitre_technique`,
`compromised_hosts`, `compromised_accounts`, `key_indicators` (≥2 verbatim
strings; empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (Domain corp.local, DC DC01.corp.local,
  Host WS-MKT-17, owner e.taylor), `zeek_dns.jsonl` (154 TXT queries, all to
  `cdn-284294b3.cloudsync-net.com` with 32-hex high-entropy labels, each
  answered with `v=<32-hex>`), `background_activity.jsonl` (routine feed).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
### 2.1 Read instruction, restate contract
- Goal: pin the deliverable shape. Action: read instruction.md.
- Observation: strict 5-key JSON, 3-value verdict taxonomy, ≥2 verbatim indicators.
- Reasoning: contract-first before evidence.
### 2.2 Inventory and read all evidence
- Goal: see the full corpus (it is small). Action: `wc -l` + full reads of ticket and both JSONL files.
- Observation: 154 TXT queries in the window, single external domain, every label a 32-hex string, every answer `v=<32-hex>`; background feed 100% routine; no pentest/engagement context.
- Reasoning: bidirectional high-entropy exchange over TXT with one destination = data channel (tunnel), not normal DNS usage.
### 2.3 Classify verdict and technique
- Goal: choose the single most important technique. Action: map behavior to ATT&CK.
- Observation: T1071.004 (Application Layer Protocol: DNS) is the exact mapping for C2 over DNS; no scanner or execution indicators that would compete.
- Reasoning: TRUE_POSITIVE_INCIDENT / T1071.004.
### 2.4 Attribute host and account
- Goal: fill hosts/accounts from evidence only. Action: check what names the artifacts carry.
- Observation: zeek_dns has only IPs; the ticket's asset inventory names WS-MKT-17 / e.taylor.
- Reasoning: hosts=["WS-MKT-17"], accounts=["e.taylor"] — ticket-sourced, not invented (noted as attribution provenance in the log).
### 2.5 Select indicators, write, validate
- Goal: ≥2 indicators robust to containment semantics; produce the file. Action: chose the CDN domain, one full high-entropy subdomain, and one `v=<hex>` answer; wrote the report in-container; validated key set, enums, types, verbatim membership of each indicator.
- Observation: all checks pass; 335 bytes.
- Reasoning: domain, query, and answer cover the channel's identity, outbound label, and inbound payload — all backslash-free strings verbatim in the JSONL.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-dns-tunnel-a` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1071.004 / ["WS-MKT-17"] / ["e.taylor"] / indicators `[cdn-284294b3.cloudsync-net.com, 987a5c332cc444fca57461161df2.cdn-284294b3.cloudsync-net.com, v=fdb74b51105c4a0c84741c5514094263]`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full DNS log (154 lines) + scan background feed.
2. Recognize: single external domain, 32-hex labels in, `v=<hex>` answers out, sustained cadence ⇒ DNS tunnel C2 ⇒ T1071.004.
3. Attribute from the ticket asset inventory (WS-MKT-17 / e.taylor) — DNS logs carry only IPs.
4. Indicators: CDN domain + one full subdomain + one `v=<hex>` answer; strict JSON; one validation pass.
### 4.2 Why optimal
One-fingerprint task; the query/answer shape settles the technique, and
domain/subdomain/answer indicators cover all three IOC angles.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
(none)
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Ticket-label indicator  [class: artifact-contract-violation]
- What it is: using `dns-entropy-volume` (the rule name, ticket-only text) as an indicator.
- Why unacceptable: fails verbatim evidence containment — this exact error burned an attempt on the -b instance of this family.
- How to avoid: indicators only from zeek_dns leaf values.
#### E-C3 Inventing host/account  [class: artifact-contract-violation]
- What it is: deriving a hostname from the source IP (e.g. 10.10.5.x subnet) or naming a user absent from artifacts.
- Why unacceptable: only the ticket asset inventory names WS-MKT-17 / e.taylor.
- How to avoid: attribute from the ticket block, cite provenance in the log.
#### E-C4 Exfil/scan technique instead of C2 protocol  [class: artifact-contract-violation]
- What it is: T1048 (exfil) or a scanning ID instead of T1071.004.
- Why unacceptable: the evidence is bidirectional beacon-like C2 over DNS, and the grader expects the C2-protocol mapping.
- How to avoid: for sustained request/response C2 over a protocol, map the Application Layer Protocol sub-technique.

## 6. Agent policy lessons
- "32-hex label in, `v=<hex>` out, one domain" is the DNS-tunnel fingerprint — volume plus shape, not any single line, is the signal.
- When the telemetry has only IPs, the ticket's asset-inventory block is the legitimate attribution source; state that provenance explicitly.
- Three-angle indicator sets (channel domain / outbound query / inbound answer) are cheap insurance and each is a clean verbatim leaf.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-dns-tunnel-a
docker exec shlepa-manual-bench-soc-dns-tunnel-a cat /app/evidence/zeek_dns.jsonl | head
# write report: T1071.004, hosts [WS-MKT-17], accounts [e.taylor], 3 indicators
docker cp tmp/manual-bench-soc-dns-tunnel-a/report.json shlepa-manual-bench-soc-dns-tunnel-a:/app/report.json
reports/tools/taskctl.sh verify bench-soc-dns-tunnel-a   # reward=1
reports/tools/taskctl.sh out bench-soc-dns-tunnel-a
```
Image: `shlepa-task-bench-soc-dns-tunnel-a:env`.
