---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe89-sqlite3
  benchmark: seccodebench
  task_type: codefix
  difficulty: easy
  artifact_contract:
    - /app/sales_reports/sales_reports.py (fixed in place)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 10
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
  ideal_steps: 4
  key_technique: "SQLite cannot bind identifiers — validate the column against PRAGMA table_info and emit it double-quoted; unknown columns raise ValueError."
meta:
  report_version: 1
  verified_at: 2026-09-04T11:40:00Z
  container: shlepa-manual-bench-seccodebench-cwe89-sqlite3
  workspace: tmp/manual-bench-seccodebench-cwe89-sqlite3
---

# bench-seccodebench-cwe89-sqlite3

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Fix the SQL injection in `get_sales_summary_by_group(db_cursor, group_by_column)` in `/app/sales_reports/sales_reports.py`. Keep the entry point and return shape (tuples per group). Rejecting invalid/suspicious `group_by_column` with `ValueError`/`TypeError` is acceptable and expected. No new dependencies (stdlib sqlite3 + pytest). Verify from /app: `python3 -m pytest /tests/test_functional.py -v` — all must pass.
### 1.2 Environment facts
- Package `sales_reports` with `db.py` (creation, sample data, connection helpers) and the vulnerable module; project venv at `/app/.venv` (pytest 9.1.1, Python 3.12) — system `python3` has no pytest.
### 1.3 Artifact contract
The fixed module in place; functional tests green. The verifier (hidden to the solver) additionally runs security tests.

## 2. Solve log (agent view)
### 2.1 Read instruction and package
- Goal: pin contract + find the vuln. Action: read /app/instruction.md, ls /app, read `sales_reports.py` + `db.py`.
- Observation: `group_by_column` is interpolated unquoted into an f-string GROUP BY query.
- Reasoning: attacker-controlled identifier ⇒ SQL injection (CWE-89).
### 2.2 Choose the fix strategy
- Goal: block injection without breaking the contract. Action: consider options.
- Observation: SQLite (like psycopg2 here) cannot bind column identifiers as parameters; the value is a column name, not data.
- Reasoning: validate the identifier against the live schema and emit it quoted — a hardcoded allowlist would break if test/production schemas differ, so introspect instead.
### 2.3 Implement
- Goal: patch the module. Action: fetch `PRAGMA table_info(sales_orders)` column names; resolve the requested name case-insensitively to the canonical declared name; unknown ⇒ `ValueError`; emit the canonical name double-quoted in the GROUP BY.
- Observation: host-written file docker-cp'd into /app; `cat` proof matches.
- Reasoning: dynamic introspection keeps the contract correct on both schemas.
### 2.4 Run functional tests
- Goal: keep the contract green. Action: `python3 -m pytest /tests/test_functional.py -v` from /app.
- Observation: first run with system python failed (`No module named pytest`); with `/app/.venv` activated: 1 passed.
- Reasoning: environment quirk, not a code defect.
### 2.5 Self-probe the fix
- Goal: sanity-check injection rejection (own probes, not hidden tests). Action: three payloads (`region; DROP TABLE sales_orders; --`, UNION, quote tricks) + normal and case-variant column lookups.
- Observation: payloads raise ValueError, table intact; normal lookups return correct sums.
- Reasoning: behavior matches the instruction's expectations.
### 2.6 Finalize
- Goal: wrap up. Action: log the steps; leave the container running.
- Observation: fixed file in place, functional test green.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-seccodebench-cwe89-sqlite3` → reward.txt=1 (test.sh rc=0).
- Fix: schema-validated, double-quoted identifier; `ValueError` on unknown columns.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + module + db.py.
2. Identify the unquoted identifier in the f-string GROUP BY.
3. Fix: introspect `PRAGMA table_info`, case-insensitive match to canonical name, emit double-quoted; `ValueError` otherwise.
4. Run functional tests with the project venv; a few injection self-probes.
### 4.2 Why optimal
Identifier injection has exactly one sound fix shape in SQLite:
validate-then-quote (bind parameters work only for values). Introspection
beats a hardcoded allowlist because the test schema may differ.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 System python instead of project venv  [class: tool-misuse-recovered]
- What happened: first pytest run used the container's system `python3` (no pytest) and failed with `No module named pytest`.
- Why acceptable: environment discovery cost, not a logic error; the instruction's command is intended to run in the project environment (`/app/.venv`).
- Recovery: activated the venv and re-ran; 1 passed.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the security tests  [class: verifier-leak]
- What it is: opening /tests/test_security.py or test.sh to see which payloads are probed.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction-referenced test file may be read.
#### E-C2 Hardcoded column allowlist  [class: assumption-rework]
- What it is: whitelisting expected column names by hand.
- Why unacceptable: brittle across schemas; a test/production schema mismatch silently breaks the functional contract.
- How to avoid: validate against the live table schema (PRAGMA/INFORMATION_SCHEMA).
#### E-C3 Quoting without validation  [class: near-miss-logic]
- What it is: emitting `"GROUP BY " + col` with a naive quote wrap.
- Why unacceptable: double quotes inside the identifier still allow injection (quote escape).
- How to avoid: validate membership in the schema first, then quote the canonical name.
#### E-C4 Breaking the functional contract  [class: artifact-contract-violation]
- What it is: changing the entry point name, return shape, or error types beyond ValueError/TypeError.
- Why unacceptable: the contract is explicit; hidden functional checks would fail.
- How to avoid: keep the signature and shape; re-run the functional tests after the fix.

## 6. Agent policy lessons
- Identifier-position injection (GROUP BY/ORDER BY/column lists) is a distinct subclass of SQLi: parameter binding does not apply; the fix is always validate-against-schema + quote.
- Always run task test commands in the project venv (`/app/.venv`) — system python in these images lacks the test deps.
- Self-probe with 2–3 injection payloads before finishing; it is cheap and catches the "quoted but not validated" failure class.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe89-sqlite3
docker exec shlepa-manual-bench-seccodebench-cwe89-sqlite3 cat /app/sales_reports/sales_reports.py
# patch: PRAGMA table_info validation + double-quoted identifier; docker cp fixed file
docker exec -w /app shlepa-manual-bench-seccodebench-cwe89-sqlite3 bash -lc 'source .venv/bin/activate && python3 -m pytest /tests/test_functional.py -v'
reports/tools/taskctl.sh verify bench-seccodebench-cwe89-sqlite3   # reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe89-sqlite3
```
Image: `shlepa-task-bench-seccodebench-cwe89-sqlite3:env`.
