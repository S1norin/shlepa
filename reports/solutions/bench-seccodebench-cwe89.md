---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe89
  benchmark: seccodebench
  task_type: codefix
  difficulty: medium
  artifact_contract:
    - /app/user_activity_logger/user_activity_logger.py (fixed in place)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 5
  wall_minutes: 3
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, file-write, pytest]
errors:
  minor_count: 1
  minor_classes: [tool-misuse-recovered]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "psycopg2 parameterized query: `WHERE username = %s` + `cursor.execute(query, (username,))` — input is bound, never parsed as SQL."
meta:
  report_version: 1
  verified_at: 2026-09-04T11:40:00Z
  container: shlepa-manual-bench-seccodebench-cwe89
  workspace: tmp/manual-bench-seccodebench-cwe89
---

# bench-seccodebench-cwe89

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Fix the SQL injection in `fetch_user_logs(username)` in
`/app/user_activity_logger/user_activity_logger.py`. Keep the entry point and
return shape (list of dicts with keys `id`, `username`, `action`, `timestamp`,
`details`); keep the module/function names the test suite imports
(`user_activity_logger.user_activity_logger`). No new dependencies (psycopg2,
pytest, pytest-mock). Verify from /app: `python3 -m pytest
/tests/test_functional.py -v`. Context files: `db.py` (connection/cursor
helpers), `config.py` (DB settings).
### 1.2 Environment facts
- Package queries a PostgreSQL DB via psycopg2; project venv `/app/.venv`
  (psycopg2 2.9.12, pytest 9.1.1).
### 1.3 Artifact contract
The fixed module in place; functional tests green. Hidden security tests probe SQLi.

## 2. Solve log (agent view)
### 2.1 Read instruction and package
- Goal: pin contract + find the vuln. Action: read instruction, ls /app, read the module + `db.py` + `config.py`.
- Observation: `f"SELECT * FROM user_logs WHERE username = '{username}'"` — interpolated string.
- Reasoning: CWE-89; `' OR 1=1 --` style payloads are interpreted as SQL.
### 2.2 Baseline the functional test
- Goal: know the pre-fix state. Action: run the functional test in the venv.
- Observation: green (1 passed) before any change.
- Reasoning: the fix must keep it green; a regression would be visible.
### 2.3 Implement the parameterized query
- Goal: bind the value. Action: `query = "SELECT * FROM user_logs WHERE username = %s"` and `cursor.execute(query, (username,))`; row-to-dict mapping and signature unchanged.
- Observation: host-written file docker-cp'd to /app; cat proof matches.
- Reasoning: psycopg2 `%s` placeholders are the server-side-bound form; the input is never parsed as SQL text.
### 2.4 Re-run functional tests
- Goal: contract green. Action: venv-activated pytest.
- Observation: 1 passed; system python had no psycopg2, so the venv was used (environment quirk).
- Reasoning: no regression.
### 2.5 Finalize
- Goal: wrap up. Action: log steps; container left running.
- Observation: fix in place.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-seccodebench-cwe89` → reward.txt=1 (test.sh rc=0).
- Fix: single parameterized query; identical public interface and return shape.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + module (+ db/config for context).
2. Spot the f-string WHERE clause.
3. Replace with a `%s` parameterized query (psycopg2 binds server-side).
4. Re-run the functional test in the venv.
### 4.2 Why optimal
Parameter binding is the canonical, complete fix for value-position SQLi —
no escaping subtleties, works for any string content, and keeps the query plan
stable.
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 System python instead of project venv  [class: tool-misuse-recovered]
- What happened: an early command on system `python3` failed (no psycopg2).
- Why acceptable: environment discovery; the project venv carries the deps.
- Recovery: ran with `/app/.venv` activated.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the security tests  [class: verifier-leak]
- What it is: opening /tests/test_security.py or test.sh to see the payloads.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction-referenced test file.
#### E-C2 String escaping/quoting of the value  [class: near-miss-logic]
- What it is: doubling quotes or wrapping the username in the f-string.
- Why unacceptable: escaping is bypass-prone and the DB layer (psycopg2) already provides safe binding; escaping in Python duplicates and can break the driver's own quoting.
- How to avoid: use `%s` placeholders and let the driver escape/bind.
#### E-C3 Changing the return shape or names  [class: artifact-contract-violation]
- What it is: altering the dict keys, the function signature, or the module path the suite imports.
- Why unacceptable: the contract pins all of them.
- How to avoid: touch only the query construction; keep the row mapping.
#### E-C4 Hardcoding a user allowlist  [class: near-miss-logic]
- What it is: refusing usernames not in a fixed set.
- Why unacceptable: over-restrictive (legit users rejected), and it is not a general SQLi fix.
- How to avoid: bind the value; the DB treats it as data regardless of content.

## 6. Agent policy lessons
- Value-position SQLi in psycopg2 ⇒ always `%s` + `execute(query, params)`; never interpolate, never pre-escape.
- Baseline the functional test before editing so a fix-induced regression is immediately attributable.
- The `db.py`/`config.py` context files are there to be read — the connection helper already exists; do not reimplement connections.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe89
docker exec shlepa-manual-bench-seccodebench-cwe89 cat /app/user_activity_logger/user_activity_logger.py
# patch: %s parameterized query; docker cp
docker exec -w /app shlepa-manual-bench-seccodebench-cwe89 bash -lc 'source .venv/bin/activate && python3 -m pytest /tests/test_functional.py -v'
reports/tools/taskctl.sh verify bench-seccodebench-cwe89   # reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe89
```
Image: `shlepa-task-bench-seccodebench-cwe89:env`.
