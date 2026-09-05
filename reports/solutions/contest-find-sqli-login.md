---
schema: shlepa.solution-report/v1
task:
  slug: contest-find-sqli-login
  benchmark: contest
  task_type: audit
  difficulty: medium
  artifact_contract:
    - /app/security_report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 13
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, curl, psql]
errors:
  minor_count: 0
  minor_classes: []
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "Full-source read → locate f-string-built queries → live read-only PoC (auth bypass + blind UNION exfiltration) → structured bug-bounty JSON with exact locations and quoted evidence."
meta:
  report_version: 1
  verified_at: 2026-09-04T17:12:00Z
  container: shlepa-manual-contest-find-sqli-login
  workspace: tmp/manual-contest-find-sqli-login
---

# contest-find-sqli-login

## 1. Task brief
### 1.1 Instruction (close paraphrase)
A FastAPI service backed by PostgreSQL runs in the container. Perform a
security audit as if preparing a bug bounty report. **Do not modify application
code.** Deliverable: valid JSON at `/app/security_report.json` with top-level
shape `{"findings": [{title, severity(critical|high|medium|low|informational),
category, location, evidence, impact, recommendation}]}` — enough detail per
finding for engineer triage.
### 1.2 Environment facts
- App source under /app: `main.py`, `db.py`, `models.py`, `routers/`
  (auth.py, items.py), own test suite /app/tests; app on :8000, Postgres local
  (appuser:apppass@localhost:5432/appdb); seeded admin/secret123 in plaintext.
### 1.3 Artifact contract
`/app/security_report.json`: strictly valid JSON, findings ordered by severity,
each with concrete evidence (quoted code / live behavior).

## 2. Solve log (agent view)
### 2.1 Read all application source
- Goal: enumerate code paths touching the DB. Action: read main.py, db.py, models.py, routers/auth.py, routers/items.py, tests.
- Observation: `routers/auth.py login()` builds the WHERE clause with an f-string on raw `req.username`/`req.password`; `db.py` seeds `admin`/`secret123` in plaintext; tokens are `token-{id}` and never validated anywhere; `update_item` uses an f-string UPDATE but only with Pydantic-bounded fields.
- Reasoning: the login SQLi is the critical finding; the rest form the report's supporting findings.
### 2.2 Prove the SQLi live (read-only)
- Goal: concrete evidence, not just code smell. Action: `POST /login` with `admin' --` → 200 `token-1` (auth bypass); blind UNION probe `x' UNION SELECT (SELECT ascii(substr(password,1,1)) FROM users WHERE username='admin') --` → token id reveals the leading char; repeat per position; length probe.
- Observation: `token-115`/`token-101`/`token-99`… recover `sec…` of the stored password; password length 9.
- Reasoning: demonstrates both bypass and data exfiltration with only SELECT-side effects.
### 2.3 Enumerate the secondary findings
- Goal: complete a triage-ready report. Action: assess storage, authz, config, token design, rate limiting.
- Observation: plaintext passwords + weak seed creds; no authorization on any endpoint (login token unused); hardcoded DB creds in db.py; predictable non-expiring tokens; no lockout; f-string UPDATE that is currently not injectable but fragile.
- Reasoning: each becomes a finding with severity, category, location, evidence, impact, recommendation.
### 2.4 Compose the JSON report
- Goal: strict contract. Action: 7 findings ordered critical → informational; evidence quotes exact code and the live PoC responses.
- Observation: `json.load`-validated on host and in-container.
- Reasoning: machine-readable, triage-ready.
### 2.5 Deliver and prove
- Goal: artifact in place. Action: host file → `docker cp /app/security_report.json` → cat proof.
- Observation: 11,685 bytes, 7 findings, in container.
- Reasoning: done.
### 2.6 Finalize
- Goal: wrap up. Action: no app code modified; PoCs were read-only SELECTs; logged steps.
- Observation: state clean.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify contest-find-sqli-login` → reward.txt=1 (test.sh rc=0).
- 7 findings; the critical SQLi in `POST /login` proven with bypass + blind exfiltration PoCs.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read all source (small app); flag every query-building site.
2. Live-read-only PoC on the login SQLi (bypass + one blind-exfil proof).
3. Fold the secondary issues (plaintext creds, missing authz, hardcoded DB creds, token design, rate limiting) into findings with severities.
4. Emit strict JSON, deliver, validate.
### 4.2 Why optimal
Small app ⇒ full-read beats fuzzing; live PoCs make the report triage-ready;
strict JSON shape is a hard contract (invalid JSON = 0).
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
None — single-pass solve.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Modifying application code  [class: constraint-violation]
- What it is: "fixing" the SQLi while auditing (the instruction forbids code changes).
- Why unacceptable: the deliverable is the report; changed code invalidates the audit and the verifier.
- How to avoid: read-only interaction with the app; artifacts only.
#### E-C2 Destructive PoC  [class: unsafe-operation]
- What it is: INSERT/UPDATE/DELETE/DROP during proof-of-concept.
- Why unacceptable: corrupts the environment the verifier runs against; an audit demonstrates with reads.
- How to avoid: SELECT-only PoCs (auth bypass via `--`, blind exfil via UNION SELECT).
#### E-C3 Invalid JSON  [class: artifact-contract-violation]
- What it is: comments, trailing commas, unescaped quotes in the report.
- Why unacceptable: the verifier parses the file strictly; malformed JSON = total failure regardless of finding quality.
- How to avoid: build the JSON programmatically and `json.load`-validate before delivery.
#### E-C4 Vague findings  [class: artifact-contract-violation]
- What it is: findings without exact location + concrete evidence (e.g. "bad SQL somewhere").
- Why unacceptable: the contract demands triage-ready detail; the verifier checks for the real issues with specifics.
- How to avoid: file/function/line + quoted code (or live response) in every finding.

## 6. Agent policy lessons
- Audit tasks: full-source read first (small apps), then prove the top finding live with read-only PoCs — code smell + demonstrated behavior is what makes a report triage-ready.
- The JSON shape is a machine contract: validate it (json.load) before delivering; severity ordering and exact locations are what graders key on.
- Keep PoCs SELECT-only; environment state is the verifier's.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-find-sqli-login   # wait until :8000/docs serves
docker exec shlepa-manual-contest-find-sqli-login cat /app/routers/auth.py
curl -s -X POST http://localhost:8000/login -H 'Content-Type: application/json' -d '{"username":"admin'\'' --","password":"x"}'   # 200 token-1
# blind: username "x' UNION SELECT (SELECT ascii(substr(password,1,1)) FROM users WHERE username='admin') --"
# write /app/security_report.json (7 findings) via docker cp; cat proof
reports/tools/taskctl.sh verify contest-find-sqli-login   # reward=1
reports/tools/taskctl.sh out contest-find-sqli-login
reports/tools/taskctl.sh down contest-find-sqli-login     # free :8000/PG for next sqli task
```
Image: `shlepa-task-contest-find-sqli-login:env`.
