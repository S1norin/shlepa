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

## Fit for Shlepa
- **Overlap:** **closest match to `contest-incident-log-forensics`**
  (log correlation → attribution/impact → remediation). Our forensics task
  is a simplified single-incident version of exactly this.
- **Offline feasibility:** high — fully containerized; no internet needed.
- **Adaptation cost:** medium — the full 55-scenario harness is heavy
  (SIEM stack); but individual scenarios (telemetry files + expected
  verdict/technique) port cheaply to Harbor tasks
  (`bench-socbench-*`) with `test.sh` checking the JSON report fields.
- **Recommendation:** mine 2–3 scenarios for dev tasks (strengthen the
  forensics family); study its verdict taxonomy (TP/FP/benign) for our
  forensics verifier — we should score "correctly says benign" too.
  Provenance caveat: independent single-maintainer project, not an
  institutional benchmark — treat scores as indicative only.

## Sources
- Repo: https://github.com/Abhiro0p/SOCBench
