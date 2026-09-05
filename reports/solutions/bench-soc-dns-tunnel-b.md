---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-dns-tunnel-b
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
  wall_minutes: 3
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
  key_technique: "Same DNS-tunnel family as -a: ~2-minute-cadence bidirectional high-entropy TXT beacon = T1071.004; indicators must be zeek leaf values, not ticket labels."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-dns-tunnel-b
  workspace: tmp/manual-bench-soc-dns-tunnel-b
---

# bench-soc-dns-tunnel-b

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3046 (opened 2026-04-25 09:15 UTC): `dns-entropy-volume` rule
flagged sustained TXT query volume with long high-entropy labels toward an
external domain during the window (source endpoint per the asset inventory).
Review `/app/evidence/`, classify the alert, write strict JSON to
`/app/report.json` with exactly 5 keys: `verdict`, `primary_mitre_technique`,
`compromised_hosts`, `compromised_accounts`, `key_indicators` (≥2 verbatim
strings; empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (Domain corp.local, Host WS-IT-11, owner
  s.garcia), `zeek_dns.jsonl` (81 TXT queries to
  `cdn-b3c16c14.cloudsync-net.com` with 32-hex high-entropy labels at ~2-minute
  cadence, each answered `v=<32-hex>`), `background_activity.jsonl` (50
  routine entries).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on one indicator): full triage correct
(TRUE_POSITIVE_INCIDENT / T1071.004 / WS-IT-11 / s.garcia) but the fourth
indicator was the ticket-only rule name `dns-entropy-volume`.
### 2.1 Confirm which indicators the JSONL evidence actually supports (attempt 2)
- Goal: establish the true leaf set. Action: python parse of `zeek_dns.jsonl`; collect all string leaves; test each current indicator for exact/substring containment.
- Observation: `dns-entropy-volume` absent from all 81 lines; the file instead contains many full high-entropy subdomains (e.g. `f8649acc3daa43619e52cdede1e0.cdn-b3c16c14.cloudsync-net.com`) as exact `query` leaves.
- Reasoning: swap the ticket label for a real beacon query string.
### 2.2 Pick the replacement leaf
- Goal: choose an unambiguous, stable leaf. Action: selected a distinct full subdomain from the query set (not the one already listed as indicator #2).
- Observation: `f8649acc3daa43619e52cdede1e0.cdn-b3c16c14.cloudsync-net.com` — exact leaf, adds a second outbound-label instance.
- Reasoning: keeps the 3-angle coverage (domain / label / answer) and gives 4 evidence-backed indicators.
### 2.3 Surgical fix
- Goal: change only that indicator. Action: `fix_report.py` on host (load JSON, replace the one list element, dump with identical formatting) → docker cp → container python.
- Observation: 401 bytes; diff vs attempt-1 report shows exactly one indicator line changed.
- Reasoning: all other fields byte-identical.
### 2.4 Validate and prove
- Goal: final contract check. Action: in-container leaf check: every one of the 4 indicators exact-leaf or substring of the JSONL; key set, enums, types asserted; `cat /app/report.json` proof.
- Observation: all four resolve verbatim; contract OK.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-dns-tunnel-b` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1071.004 / ["WS-IT-11"] / ["s.garcia"] / indicators `[cdn-b3c16c14.cloudsync-net.com, a86b9be719b440798b9ecf565487.cdn-b3c16c14.cloudsync-net.com, v=9c43a09d2b274cb19ff5f28411d6278f, f8649acc3daa43619e52cdede1e0.cdn-b3c16c14.cloudsync-net.com]`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + full zeek DNS log (81 lines) + scan background feed.
2. Classify: sustained ~2-minute-cadence bidirectional high-entropy TXT beacon to one external domain ⇒ DNS tunnel C2 ⇒ T1071.004; TRUE_POSITIVE_INCIDENT.
3. Attribute WS-IT-11 / s.garcia from the ticket asset inventory.
4. Indicators strictly from zeek leaves (domain, two full subdomains, one `v=<hex>` answer); strict JSON; one validation pass — no ticket/rule names.
### 4.2 Why optimal
Identical shape to the -a instance; the only real trap is indicator purity
(ticket labels are not evidence), which a leaf check catches pre-submission.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Ticket-label indicator  [class: near-miss-logic]
- What happened: attempt 1 included `dns-entropy-volume` — the alert rule name from the ticket — as the fourth indicator; it is not a value in the JSONL evidence.
- Why acceptable: three of four indicators were correct evidence leaves and all other fields were accepted; the rule name is a plausible "indicator" from an analyst's perspective, so this is a near-miss on the verbatim clause rather than a wrong analysis.
- Recovery: mechanical swap to a verified exact leaf (`f8649acc…` subdomain); byte-identical elsewhere; reward=1.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Non-verbatim indicator  [class: artifact-contract-violation]
- What it is: any indicator (ticket label, paraphrase, constructed string) not present in the evidence files.
- Why unacceptable: violates the explicit verbatim clause and costs a full attempt.
- How to avoid: run a leaf-containment check on every indicator before finalizing — make it a hard gate, not a judgment call.
#### E-C3 Inventing host/account  [class: artifact-contract-violation]
- What it is: deriving host/user from source IPs or naming users absent from artifacts.
- Why unacceptable: only the ticket asset inventory names WS-IT-11 / s.garcia.
- How to avoid: attribute from the ticket block with provenance noted.
#### E-C4 Benign explanation without evidence  [class: near-miss-logic]
- What it is: calling high-entropy TXT volume "routine monitoring" — no artifact supports an authorized source.
- Why unacceptable: the volume+shape pattern is a C2 signature; the benign verdict is unsupported.
- How to avoid: weigh cadence + entropy + destination uniqueness; absence of a benign explanation in the artifacts is itself evidence.

## 6. Agent policy lessons
- The verbatim clause is machine-checked against the evidence files only: ticket text, rule names, and prose never count. Treat "is this string in the JSONL?" as a programmatic gate for every indicator.
- Family instances share the mapping (dns-tunnel ⇒ T1071.004); re-verify per-instance facts only.
- For beacon-shaped data, listing two different label instances strengthens IOC coverage without any extra cost.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-dns-tunnel-b
docker exec shlepa-manual-bench-soc-dns-tunnel-b cat /app/evidence/zeek_dns.jsonl | head
# fix: replace ticket-label indicator with a verified zeek leaf; keep 4 indicators
docker cp tmp/manual-bench-soc-dns-tunnel-b/fix_report.py shlepa-manual-bench-soc-dns-tunnel-b:/tmp/fix_report.py
docker exec shlepa-manual-bench-soc-dns-tunnel-b python /tmp/fix_report.py
docker exec shlepa-manual-bench-soc-dns-tunnel-b cat /app/report.json   # proof
reports/tools/taskctl.sh verify bench-soc-dns-tunnel-b   # reward=1
reports/tools/taskctl.sh out bench-soc-dns-tunnel-b
```
Image: `shlepa-task-bench-soc-dns-tunnel-b:env`.
