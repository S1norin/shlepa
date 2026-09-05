---
schema: shlepa.solution-report/v1
task:
  slug: contest-incident-log-forensics
  benchmark: contest
  task_type: forensics
  difficulty: hard
  artifact_contract:
    - /app/incident_report.txt
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 7
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, jq, python, grep]
errors:
  minor_count: 0
  minor_classes: []
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 5
  key_technique: "Reconcile the truncated primary audit against the WORM/SIEM fragment within the documented gap; attribute via the only successful SSH brute-force (deploysvc @ 14:03:40Z from 203.0.113.50); the primary exfil is the recovered sensitive_export telemetry-lolt-441 4.9s later; attacker IP = true client in the matched proxy XFF chain."
meta:
  report_version: 1
  verified_at: 2026-09-04T18:00:00Z
  container: shlepa-manual-contest-incident-log-forensics
  workspace: tmp/manual-contest-incident-log-forensics
---

# contest-incident-log-forensics

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Ticket IR-2026-0501: DLP noise on **api-3** around May 1, 2026. Disk sync during
containment **truncated** the primary application audit mid-incident; a
**SIEM/WORM fragment** was later attached. Review everything under
`/app/incident/` (collector_note.txt; app.jsonl + app_audit_recovered.jsonl;
proxy_access.log; edge_decisions.log + edge_decisions_fragment.log;
dns_ptr_hints.txt (context only); auth.log on prod-auth-01), reconcile the
story, and write **`/app/incident_report.txt`** — UTF-8, **exactly four**
non-empty `key=value` lines (no spaces around `=`, no blank lines, no
commentary), keys exactly: `attacker_ip`, `compromised_user`, `exfil_bytes`,
`first_malicious_event_utc`. Normative mapping: `compromised_user` = the
record's `identity.subject`; `exfil_bytes` = `audit.payload_logical_bytes` if
present else `audit.bytes`; `first_malicious_event_utc` = the record's `ts`
verbatim (ISO 8601 UTC with fractional seconds); `attacker_ip` = derived from
proxy_access.log for the matched HTTP request using the XFF.
### 1.2 Environment facts
- `app.jsonl` (~5.8 MB) truncated with a content gap around the suspected
  exfil minute; `app_audit_recovered.jsonl` is the same-schema WORM fragment
  covering the gap; edge decisions split into a main shard + a late replay
  shard; auth.log in EDT (UTC−4); proxy log is load-balanced (XFF chains with
  LB/gateway hops); dns_ptr_hints.txt is passive context only.
### 1.3 Artifact contract
`/app/incident_report.txt`: exactly 4 machine lines; the attributed **primary**
exfiltration event.

## 2. Solve log (agent view)
### 2.1 Read the collector note and inventory
- Goal: know what broke before trusting any record. Action: ls; read collector_note.txt.
- Observation: primary audit truncated mid-sync with a gap around the suspected minute; WORM fragment attached; edge export in two parts (main + late replay shard).
- Reasoning: the true exfil record must be sought in the fragment's gap region.
### 2.2 Reconstruct the intrusion from auth.log
- Goal: who/when/from where. Action: read auth.log (EDT → UTC).
- Observation: SSH brute-force for `deploysvc` from 198.51.100.0/24 and 203.0.113.0/24 (10:03:11–10:03:35 EDT, many failures); the **only success**: 10:03:40 EDT = 14:03:40Z, `Accepted password for deploysvc from 203.0.113.50`.
- Reasoning: attacker = 203.0.113.50; compromised account = deploysvc; attribution window opens 14:03:40Z.
### 2.3 Merge edge shards and map dispositions
- Goal: disposition context per request_id. Action: read both edge shards (note EDT offsets), merge.
- Observation: dispositions per request id; the late replay shard carries the `CONFIRM_SENSITIVE` call for the gap-region record.
- Reasoning: dispositions separate incident traffic from sanctioned/bulk/watchlist traffic.
### 2.4 Reconcile the audit and pick the primary exfil
- Goal: the attributed primary exfiltration. Action: scan primary + fragment for `sensitive_export` around the gap; cross with auth timeline, edge dispositions, and proxy XFF matches.
- Observation: `rid=telemetry-lolt-441` (recovered, sensitive_export, ts `2026-05-01T14:03:44.900Z`, subject `deploysvc`, `payload_logical_bytes=2457600` vs wire `bytes=18432`) — the only sensitive_export in the gap, 4.9s after the successful login, CONFIRM_SENSITIVE. Decoys rejected: `legacy-bulk-77` (nightly scheduled, ALLOW_BULK_LEGACY), `soc-daily-archive-09` (sanctioned internal), `dup-export-internal` (900B break-glass), `xff-amb` (WATCHLIST_ONLY), `after-window` (post-window, 9999999, no proxy/edge record).
- Reasoning: attribution (login→seconds→export), disposition, and byte semantics all converge.
### 2.5 Derive the attacker IP from the matched proxy request
- Goal: the normative XFF answer. Action: find the HTTP request for telemetry-lolt-441 in proxy_access.log; parse the XFF chain.
- Observation: chain includes LB 10.0.0.5 / gateway 198.51.100.1 hops; the true client is 203.0.113.50 (consistent with the successful SSH source).
- Reasoning: standard XFF semantics past the LB/gateway hops; cross-confirmed by auth.log.
### 2.6 Compose and deliver the report
- Goal: strict 4-line file. Action: map fields per normative rules (`payload_logical_bytes` preferred; `ts` verbatim); write host file; docker cp; cat proof.
- Observation: `attacker_ip=203.0.113.50` / `compromised_user=deploysvc` / `exfil_bytes=2457600` / `first_malicious_event_utc=2026-05-01T14:03:44.900Z`; od-verified format (4 lines, no spaces, single trailing newline).
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify contest-incident-log-forensics` → reward.txt=1 (test.sh rc=0).
- Report: the four lines above; primary exfil = recovered record telemetry-lolt-441.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Collector note → understand truncation/gap and the fragment's role.
2. auth.log → attacker IP + compromised account + window start (14:03:40Z).
3. Merge edge shards → dispositions; reconcile primary vs fragment in the gap → the sensitive_export seconds after login is the primary exfil.
4. Match the HTTP request in the proxy log → true client XFF.
5. Emit the strict 4-line file (verbatim ts, payload_logical_bytes).
### 4.2 Why optimal
Every field has a normative source; the reconciliation is what separates the
primary event from the six decoys (scheduled, sanctioned, break-glass,
watchlist, post-window, ambiguous-XFF records).
### 4.3 Estimated ideal steps: 5

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
None — single-pass solve with explicit decoy rejection.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Picking a decoy exfil record  [class: near-miss-logic]
- What it is: reporting a scheduled/bulk/sanctioned/watchlist/post-window export (legacy-bulk-77, soc-daily-archive-09, dup-export-internal, xff-amb, after-window) as the primary incident.
- Why unacceptable: the task asks for the *attributed primary* exfiltration; decoys are planted to catch timeline/disposition mismatches.
- How to avoid: require all three to align: inside the attribution window (after the successful login), CONFIRM_SENSITIVE disposition, and a matching proxy/edge record.
#### E-C2 Wrong XFF hop as attacker IP  [class: near-miss-logic]
- What it is: reporting an LB (10.0.0.5) or gateway (198.51.100.1) hop instead of the true client.
- Why unacceptable: the normative rule is the true client per XFF semantics; internal hops are infrastructure, not the attacker.
- How to avoid: walk the chain past the known LB/gateway hops; cross-check against the SSH source in auth.log.
#### E-C3 Wrong byte field  [class: artifact-contract-violation]
- What it is: using wire `bytes` (18432) instead of `payload_logical_bytes` (2457600) when both are present.
- Why unacceptable: the normative mapping prefers `payload_logical_bytes` when present.
- How to avoid: apply the mapping exactly; the field precedence is part of the spec.
#### E-C4 Format violations  [class: artifact-contract-violation]
- What it is: extra keys, spaces around `=`, blank lines, commentary, or a reformatted timestamp (losing fractional seconds).
- Why unacceptable: the verifier parses the file strictly; `ts` must be copied verbatim.
- How to avoid: copy `ts` byte-for-byte; validate with od/line count before delivery.

## 6. Agent policy lessons
- Start with the collector note: it defines the evidentiary topology (truncation gap + fragment) and tells you where the truth can only exist.
- The SSH success line is the attribution anchor: IP + account + window in one line; everything else is corroboration or decoy.
- Decoys are classified by disposition + timeline + cross-source match, never by size alone (the biggest record, after-window, is a trap).
- Strict machine formats: copy timestamps verbatim, apply field precedence exactly, validate the file byte-level (od) before delivery.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-incident-log-forensics
docker exec shlepa-manual-contest-incident-log-forensics cat /app/incident/collector_note.txt
docker exec shlepa-manual-contest-incident-log-forensics cat /app/incident/auth.log        # 14:03:40Z accepted deploysvc from 203.0.113.50
docker exec shlepa-manual-contest-incident-log-forensics bash -lc "grep -h . /app/incident/edge_decisions*.log"
docker exec shlepa-manual-contest-incident-log-forensics bash -lc "grep telemetry-lolt-441 /app/incident/app_audit_recovered.jsonl /app/incident/proxy_access.log"
# write the 4-line report (host) -> docker cp /app/incident_report.txt; od -c proof
reports/tools/taskctl.sh verify contest-incident-log-forensics   # reward=1
reports/tools/taskctl.sh out contest-incident-log-forensics
reports/tools/taskctl.sh down contest-incident-log-forensics
```
Image: `shlepa-task-contest-incident-log-forensics:env`.
