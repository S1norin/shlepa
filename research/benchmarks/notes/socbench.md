# SOCBench

- **Category:** soc (blue-team / incident triage)
- **Source:** github.com/Abhiro0p/SOCBench (single-maintainer project, no
  paper; active as of 2026-05)
- **Code:** https://github.com/Abhiro0p/SOCBench
- **Reviewed:** 2026-08-27

## What it tests
LLMs as **Tier 1–3 SOC analysts** on **55 real attack scenarios**. Each
scenario presents **raw, unlabeled security telemetry** (Windows Event
Logs, Sysmon, Zeek, CloudTrail); the model must produce a structured JSON
investigation report: verdict (true positive / false positive / benign
anomaly), MITRE ATT&CK attack chain with evidence citations, compromised
assets, impact/blast radius, ordered containment steps, a **Sigma detection
rule**, and a reasoning trace citing timestamps/event IDs.

## Environment
Fully **containerized, end-to-end** stack: Elasticsearch+Kibana as
SIEM/telemetry store, LocalStack (AWS sim), PostgreSQL results DB, FastAPI
+ React dashboard. Runs any LLM (Claude, OpenAI, Ollama); includes RAG and
LoRA fine-tuning paths for systematic improvement.

## Tasks
55 curated attack scenarios; scored across 5 reasoning dimensions
(detection, MITRE mapping, impact assessment, Sigma rule quality, reasoning).

## Scoring
Structured-output scoring over the JSON report (5 dimensions); verdict
precision matters — false positives are an explicit category (benign
anomaly handling is scored, not ignored).

## Vendored into this repo

Adapted on 2026-08-28 and 2026-08-29 (upstream @ `4d96147`, MIT). Per the
recommendation below, scenarios were mined covering the two verdict classes
that exist in the v1 data (the index holds 45 scenarios: 39
`TRUE_POSITIVE_INCIDENT`, 6 `FALSE_POSITIVE_AUTHORIZED_PENTEST`, no
`BENIGN_ANOMALY` scenario yet; the repo advertises 55). 18 scenarios are
vendored in total: the two below with per-task contracts, plus 16 hard
scenarios sharing the strict five-field contract.

| task | scenario | difficulty (upstream label) | graded report fields |
|------|----------|-----------------------------|----------------------|
| `bench-soc-scanner-fp` | SCN-029 — port sweep from the pentest VLAN (Zeek conn log + change-management context) | easy | verdict, flagged source IP, within-approved-window flag |
| `bench-soc-ntds-vss` | SCN-012 — NTDS.dit via volume shadow copy on DC01 (event logs + background noise) | hard | verdict, MITRE technique, exact host/account attribution, evidence-verbatim IOCs |

The 16 hard scenarios (synced 2026-08-29) are all `TRUE_POSITIVE_INCIDENT`
and grade the strict five-field contract: `verdict`,
`primary_mitre_technique`, `compromised_hosts`, `compromised_accounts`,
`key_indicators` (each verbatim in the evidence, with per-task IOC keyword
coverage). The `-a`/`-b` suffixes mark two independently generated instances
of the same scenario family (different hosts, accounts, telemetry seeds):

| task | scenario | primary MITRE technique |
|------|----------|-------------------------|
| `bench-soc-rdp-ptt-a` | SCN-016 — RDP pass-the-ticket lateral movement (LogonType 10 + matching 3389 session) | T1021.001 |
| `bench-soc-rdp-ptt-b` | SCN-036 — RDP pass-the-ticket lateral movement (second instance) | T1021.001 |
| `bench-soc-dll-hijack-a` | SCN-019 — unsigned system DLL loaded from a writable application directory | T1574.001 |
| `bench-soc-dll-hijack-b` | SCN-039 — unsigned system DLL loaded from a writable application directory (second instance) | T1574.001 |
| `bench-soc-proc-hollow-a` | SCN-021 — CreateRemoteThread from a user-profile svchost.exe into a signed service | T1055.012 |
| `bench-soc-proc-hollow-b` | SCN-041 — CreateRemoteThread into a signed system service (second instance) | T1055.012 |
| `bench-soc-amsi-bypass-a` | SCN-022 — AMSI-bypass script block + amsi.dll write patch | T1562.001 |
| `bench-soc-amsi-bypass-b` | SCN-042 — AMSI-bypass script block + amsi.dll write patch (second instance) | T1562.001 |
| `bench-soc-aws-passrole-a` | SCN-023 — CloudTrail PassRole + Lambda backdoor from an external IP | T1098.003 |
| `bench-soc-aws-passrole-b` | SCN-043 — CloudTrail PassRole + Lambda backdoor (second instance) | T1098.003 |
| `bench-soc-dns-tunnel-a` | SCN-026 — high-entropy DNS TXT tunneling C2 | T1071.004 |
| `bench-soc-dns-tunnel-b` | SCN-046 — high-entropy DNS TXT tunneling C2 (second instance) | T1071.004 |
| `bench-soc-https-beacon-a` | SCN-027 — periodic HTTPS beaconing to a single external endpoint | T1071.001 |
| `bench-soc-https-beacon-b` | SCN-047 — periodic HTTPS beaconing (second instance) | T1071.001 |
| `bench-soc-ntds-vss-a` | SCN-032 — NTDS.dit via volume shadow copy on DC01 | T1003.003 |
| `bench-soc-ntds-vss-b` | SCN-052 — NTDS.dit via volume shadow copy on DC01 (second instance) | T1003.003 |

Adaptation decisions (see `tasks/README.md`, SOCBench subset section):
- telemetry becomes static JSONL fixtures in `environment/evidence/`;
  upstream answer-key fields (`ground_truth_label`, `analyst_note`) stripped,
  matching how the upstream harness builds its prompt;
- the LLM judge is replaced by a deterministic field-by-field grader
  (`tests/report_grader.py`) over a strict JSON report at `/app/report.json`,
  using the upstream verdict taxonomy;
- upstream `background_noise` is kept as context for the hard task (the
  upstream harness excludes it from the prompt; including it adds realistic
  correlation work without changing the answer).

## Fit for Shlepa
- **Overlap:** **closest match to `contest-incident-log-forensics`**
  (log correlation → attribution/impact → remediation). Our forensics task
  is a simplified single-incident version of exactly this.
- **Offline feasibility:** high — fully containerized; no internet needed.
- **Adaptation cost:** medium — the full 55-scenario harness is heavy
  (SIEM stack); but individual scenarios (telemetry files + expected
  verdict/technique) port cheaply to Harbor tasks
  (`bench-socbench-*`) with `test.sh` checking the JSON report fields.
- **Recommendation:** mine scenarios for dev tasks (strengthen the
  forensics family) — done in 2026-08 (18 of the 45 indexed scenarios
  vendored, all hard except SCN-029; further instances can be added the same
  way if the forensics family needs more coverage). Study its verdict
  taxonomy (TP/FP/benign) for our forensics verifier — we should score
  "correctly says benign" too (the v1 data has no `BENIGN_ANOMALY` scenario,
  so the class is currently unexercised). Provenance caveat: independent
  single-maintainer project, not an institutional benchmark — treat scores
  as indicative only.

## Sources
- Repo: https://github.com/Abhiro0p/SOCBench
