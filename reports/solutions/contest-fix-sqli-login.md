---
schema: shlepa.solution-report/v1
task:
  slug: contest-fix-sqli-login
  benchmark: contest
  task_type: fix
  difficulty: easy
  artifact_contract:
    - /app/routers/auth.py (parameterized login query; all /app/tests passing)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 10
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, file-write, pytest, curl]
errors:
  minor_count: 1
  minor_classes: [near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "asyncpg parameterized query: fetchrow('SELECT id FROM users WHERE username = $1 AND password = $2', username, password); restart the app; run the test suite."
meta:
  report_version: 1
  verified_at: 2026-09-04T17:32:00Z
  container: shlepa-manual-contest-fix-sqli-login
  workspace: tmp/manual-contest-fix-sqli-login
---

# contest-fix-sqli-login

## 1. Task brief
### 1.1 Instruction (close paraphrase)
A FastAPI service backed by PostgreSQL runs in the container. Run `pytest
tests/` (the app's own suite at /app/tests) — **all tests must still pass**
after your changes. Analyse the code, identify the most critical security
issues, and fix them. No new dependencies beyond `pyproject.toml`.
### 1.2 Environment facts
- App under /app: main.py, db.py, models.py, routers/ (auth.py, items.py),
  /app/tests (15 tests); asyncpg pool; seeded admin/secret123 (plaintext,
  pinned by the test contract).
- Only the login query was f-string-built; all other queries were already
  parameterized.
### 1.3 Artifact contract
The fixed code in place (minimal diff), functional contract intact (15/15
tests), injection neutralized.

## 2. Solve log (agent view)
### 2.1 Read all source
- Goal: find every query-building site. Action: read main.py, db.py, models.py, routers/auth.py, routers/items.py, tests, pyproject.
- Observation: `routers/auth.py login()` interpolates username/password into an f-string SELECT; everything else uses placeholders; tests pin seeded admin/secret123 login behavior.
- Reasoning: login SQLi is the sole injection point; fix = parameterize.
### 2.2 Design the fix within the test contract
- Goal: keep the contract. Action: keep the endpoint, token shape `token-{id}`, and 401-on-failure; replace the f-string with `fetchrow("SELECT id FROM users WHERE username = $1 AND password = $2", req.username, req.password)`.
- Observation: plaintext password storage is also a real issue, but hashing would break the seeded-credential test contract (needs a migration) — out of scope for "keep all tests passing".
- Reasoning: minimal diff; security priority order: injection first, contract-pinned behavior untouched.
### 2.3 Apply the fix
- Goal: deliver the change. Action: host-write the fixed auth.py → docker cp → cat proof.
- Observation: single-function diff.
- Reasoning: traceable write, no heredoc no-op risk.
### 2.4 Restart the app
- Goal: make the change live. Action: found the running uvicorn still serving old code; restarted it.
- Observation: fresh process serves the fixed endpoint.
- Reasoning: the verifier probes the live app; a stale process would fail the security check.
### 2.5 Run the test suite
- Goal: prove the contract. Action: `pytest tests/` from /app in the container venv.
- Observation: 15 passed.
- Reasoning: functional contract intact.
### 2.6 Probe the fix
- Goal: confirm neutralization. Action: injection payloads (`' OR '1'='1`, `'--`, `OR 1=1; --`) → 401; `admin`/`secret123` → 200 `token-1`; DB restored to seed state.
- Observation: injection dead, contract alive.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify contest-fix-sqli-login` → reward.txt=1 (test.sh rc=0).
- Fix: parameterized asyncpg query in `login()`; 15/15 app tests pass.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Full source read → single injection site identified (login).
2. Parameterize with `$1`/`$2`; restart the app.
3. `pytest tests/` green; quick payload probes.
### 4.2 Why optimal
One-function fix; the test suite is the contract oracle; the plaintext
passwords are pinned by the seeded tests, so touching them is scope creep.
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Stale app process  [class: near-miss-logic]
- What happened: after editing auth.py, the running uvicorn still served the old (vulnerable) code until it was restarted.
- Why acceptable: standard deploy mechanics; caught by probing after the edit, before finishing.
- Recovery: restarted uvicorn; re-probed.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the hidden verifier  [class: verifier-leak]
- What it is: opening /tests/* (container root) to see the security probes.
- Why unacceptable: breaks simulation fidelity; /app/tests (the app's own suite) is in scope, /tests is not.
- How to avoid: keep the two test trees separate in your head and in your commands.
#### E-C2 Escaping instead of parameterizing  [class: near-miss-logic]
- What it is: sanitizing/escaping the inputs and keeping the f-string.
- Why unacceptable: escaping is bypass-prone; asyncpg provides native binding, so there is no reason to interpolate.
- How to avoid: `fetchrow(query, *params)` with `$1`/`$2` placeholders, always.
#### E-C3 Breaking the functional contract  [class: artifact-contract-violation]
- What it is: changing the token shape, the 401 semantics, or "fixing" plaintext storage in a way that breaks seeded-credential tests.
- Why unacceptable: the instruction requires all tests to still pass; the verifier checks functionality alongside security.
- How to avoid: run `pytest tests/` after the change; keep the diff minimal.
#### E-C4 Not restarting the service  [class: functionality-broken]
- What it is: finishing with the fixed file on disk but the vulnerable process still serving.
- Why unacceptable: the verifier probes the live app; the unfixed process fails the security check.
- How to avoid: after any code change, restart the app and re-probe live.

## 6. Agent policy lessons
- "Fix the critical issues, keep all tests passing" ⇒ the test suite is the contract oracle; identify which behaviors are pinned before deciding scope (plaintext seed creds are pinned → leave, document).
- asyncpg fix shape: `fetchrow("... $1 ... $2 ...", a, b)` — never f-strings, never manual escaping.
- Code edits in a running service container require a restart + live re-probe; file-on-disk is not the artifact, the running behavior is.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-fix-sqli-login   # wait until :8000 serves
docker exec shlepa-manual-contest-fix-sqli-login cat /app/routers/auth.py
# fix: fetchrow("SELECT id FROM users WHERE username = $1 AND password = $2", req.username, req.password); docker cp auth.py
# restart uvicorn; run: cd /app && <venv> python -m pytest tests/   # 15 passed
# probes: ' OR '1'='1 / ' -- / OR 1=1; --  -> 401; admin/secret123 -> 200 token-1
reports/tools/taskctl.sh verify contest-fix-sqli-login   # reward=1
reports/tools/taskctl.sh out contest-fix-sqli-login
reports/tools/taskctl.sh down contest-fix-sqli-login     # free :8000/PG
```
Image: `shlepa-task-contest-fix-sqli-login:env`.
