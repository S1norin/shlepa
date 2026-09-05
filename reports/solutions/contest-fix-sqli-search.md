---
schema: shlepa.solution-report/v1
task:
  slug: contest-fix-sqli-search
  benchmark: contest
  task_type: fix
  difficulty: easy
  artifact_contract:
    - /app/routers/items.py (parameterized search query; all /app/tests passing)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 7
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, file-write, pytest, curl]
errors:
  minor_count: 0
  minor_classes: []
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "Build the LIKE pattern in Python (f\"%{q}%\") and bind it as $1 — the user value never enters the SQL string; restart the app; run the test suite."
meta:
  report_version: 1
  verified_at: 2026-09-04T17:45:00Z
  container: shlepa-manual-contest-fix-sqli-search
  workspace: tmp/manual-contest-fix-sqli-search
---

# contest-fix-sqli-search

## 1. Task brief
### 1.1 Instruction (close paraphrase)
A FastAPI service backed by PostgreSQL runs in the container (a search
service). Run `pytest tests/` (the app's own suite at /app/tests) — **all
tests must still pass** after your changes. Analyse the code, identify the
most critical security issues, and fix them. No new dependencies beyond
`pyproject.toml`.
### 1.2 Environment facts
- App under /app: main.py, db.py, models.py, routers/ (auth, items, comments,
  tags, users), /app/tests (15 tests); asyncpg pool; the only f-string-built
  query is `GET /search` in routers/items.py.
### 1.3 Artifact contract
The fixed code in place (minimal diff), 15/15 tests passing, injection on the
search endpoint neutralized, normal search behavior preserved.

## 2. Solve log (agent view)
### 2.1 Read all source
- Goal: find every query-building site. Action: read main.py, db.py, models.py, all routers, tests, pyproject.
- Observation: `GET /search` in routers/items.py concatenates `LIKE '%{q}%'` into the SQL with an f-string; all other queries already parameterized.
- Reasoning: single injection point, value-position inside a LIKE pattern.
### 2.2 Design the fix
- Goal: keep behavior, kill injection. Action: build the pattern in Python (`f"%{q}%"`) and bind it: `conn.fetch("SELECT * FROM items WHERE name LIKE $1 ORDER BY id ASC", pattern)`; keep `ORDER BY id ASC` (literal, no user input).
- Observation: no identifier (column/order) is user-controlled, so no allowlist is needed — pure value binding suffices.
- Reasoning: minimal diff; identical result sets for all clean inputs.
### 2.3 Apply the fix
- Goal: deliver the change. Action: host-write the fixed items.py → docker cp → cat proof (+ `ast.parse` sanity).
- Observation: single-function diff in `search()`.
- Reasoning: traceable write.
### 2.4 Restart the app
- Goal: fixed code live. Action: restarted uvicorn; /healthz OK.
- Observation: new process serves the patched endpoint.
- Reasoning: the verifier probes the live app.
### 2.5 Run the test suite
- Goal: contract proof. Action: `pytest tests/` from /app (container env).
- Observation: 15 passed.
- Reasoning: functional contract intact.
### 2.6 Probe live
- Goal: confirm neutralization + behavior. Action: normal queries (`q=timeout`, `q=bug`, `q=`) return the expected rows; payloads (`' OR 1=1--`, `' UNION SELECT 999,… --`, `%' OR '1'='1`, lone `'`) → 0 rows, no 500s, no injected rows.
- Observation: injection inert, behavior preserved.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify contest-fix-sqli-search` → reward.txt=1 (test.sh rc=0).
- Fix: `GET /search` binds the LIKE pattern as `$1`; 15/15 tests pass.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Full source read → single injection site (search LIKE pattern).
2. Bind the pattern as a parameter (build the `%…%` in Python); restart.
3. `pytest tests/` + payload probes.
### 4.2 Why optimal
One-function fix; LIKE wildcards belong to the *value*, so Python-side
pattern construction + `$1` binding is the canonical, complete fix.
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
None — single-pass solve.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the hidden verifier  [class: verifier-leak]
- What it is: opening /tests/* (container root) to see the security probes.
- Why unacceptable: breaks simulation fidelity; /app/tests is in scope, /tests is not.
- How to avoid: keep the two test trees strictly separate.
#### E-C2 Escaping the input inside the f-string  [class: near-miss-logic]
- What it is: escaping quotes/percent signs and keeping the interpolation.
- Why unacceptable: escaping LIKE metacharacters/quotes is fiddly and bypass-prone; the driver already provides safe binding.
- How to avoid: bind the whole pattern as `$1`; never interpolate values.
#### E-C3 Breaking search semantics  [class: artifact-contract-violation]
- What it is: changing the matching behavior (case sensitivity, ordering, empty-query behavior) while "fixing".
- Why unacceptable: the 15-test contract pins the behavior; the verifier checks functionality alongside security.
- How to avoid: keep the query shape identical (same columns, same ORDER BY, same LIKE semantics); run the suite.
#### E-C4 Finishing with a stale process  [class: functionality-broken]
- What it is: leaving the old uvicorn serving the vulnerable code after editing.
- Why unacceptable: the verifier probes the live app.
- How to avoid: restart after edits; re-probe live.

## 6. Agent policy lessons
- LIKE-pattern injection: the wildcards are part of the *value* — construct the full pattern in application code and bind it; no escaping, no allowlist needed when no identifier is user-controlled.
- Same discipline as the sibling login task: full source read → minimal parameterized diff → restart → test suite → live probes.
- The app's own test suite is the functional contract oracle; run it before and after.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-fix-sqli-search   # wait until :8000 serves
docker exec shlepa-manual-contest-fix-sqli-search sed -n '1,25p' /app/routers/items.py
# fix: conn.fetch("SELECT * FROM items WHERE name LIKE $1 ORDER BY id ASC", f"%{q}%"); docker cp items.py; restart uvicorn
# cd /app && <venv> python -m pytest tests/   # 15 passed
# probes: q=%27%20OR%201%3D1-- -> 0 rows; q=timeout -> expected row
reports/tools/taskctl.sh verify contest-fix-sqli-search   # reward=1
reports/tools/taskctl.sh out contest-fix-sqli-search
reports/tools/taskctl.sh down contest-fix-sqli-search     # free :8000/PG
```
Image: `shlepa-task-contest-fix-sqli-search:env`.
