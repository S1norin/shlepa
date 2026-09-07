---
schema: shlepa.solution-report/v1
task:
  slug: contest-find-xss-python
  benchmark: contest
  task_type: audit
  difficulty: easy
  artifact_contract:
    - /app/security_report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 3
  wall_minutes: 5
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-exec, docker-cp]
errors:
  minor_count: 0
  minor_classes: []
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "Full read of the 12-line app → spot the unescaped f-string reflection (parse_qs → f-string → text/html) → in-process PoC without touching the app → strict JSON report naming CWE-79, route, line 8, PoC evidence, and the html.escape repair."
meta:
  report_version: 1
  verified_at: 2026-09-06T18:43:08Z
  container: shlepa-manual-contest-find-xss-python
  workspace: tmp/manual-contest-find-xss-python
---

# Solution report: contest-find-xss-python

## 1. Task brief (agent view)
### 1.1 Instruction (close paraphrase)
A small Python web application lives under `/app/src/` inside the container.
Perform a security audit and identify the **deliberately planted security
logic defect**. **Do not modify the application.** Deliverable: a valid JSON
report at `/app/security_report.json` with top-level shape
`{"findings": [{title, severity(critical|high|medium|low|informational),
category, location, evidence, impact, recommendation}]}`. The report must
name the applicable CWE, identify the affected route and source line or
expression, explain how attacker-controlled input reaches the dangerous
output, and recommend a concrete repair.
### 1.2 Environment facts
- Single-file app: `/app/src/app.py` (12 lines); plain Python, no framework,
  no template engine, no escaping anywhere.
- No running service required to reach the logic: the route handler
  `preview_note(query_string)` is an ordinary function (route table
  `ROUTES = {"GET /preview": preview_note}`, line 12), so it can be exercised
  by direct import in a throwaway process.
- No other endpoints, no DB, no auth, no tests shipped under /app.
### 1.3 Artifact contract
`/app/security_report.json`: strictly valid JSON, `findings` list, each
finding with all 7 keys and concrete content — CWE name, affected route,
exact source line/expression, input→output path, impact, concrete repair.

## 2. Solve log (agent view)
### 2.1 Explore the app
- Goal: minimal discovery of the code surface.
- Action: `ls /app`, `find /app/src -type f`, `cat -n /app/src/app.py` via `docker exec`.
- Observation: single file `/app/src/app.py` (12 lines). `preview_note(query_string)` parses `note` via `parse_qs` (line 7), builds `page = f"<main><h1>Preview</h1><p>{note}</p></main>"` (line 8), returns `200, {"Content-Type": "text/html; charset=utf-8"}, page.encode()` (line 9). Route table `ROUTES = {"GET /preview": preview_note}` (line 12).
- Reasoning: a user-controlled value interpolated raw into an HTML document served as `text/html` — textbook reflected XSS. No other endpoints, no template engine, no escaping anywhere. This is the planted defect.
### 2.2 Confirm exploitability in-process (no modification)
- Goal: verify attacker input actually reaches the dangerous output.
- Action: from `/tmp` inside the container (separate process, nothing written under /app/src): `python3 -c "import sys; sys.path.insert(0,'/app/src'); from app import preview_note; print(preview_note('note=<img src=x onerror=alert(document.cookie)>'))"`.
- Observation: `200 {'Content-Type': 'text/html; charset=utf-8'}` and body `<main><h1>Preview</h1><p><img src=x onerror=alert(document.cookie)></p></main>` — payload echoed verbatim, unescaped, inside `<p>`.
- Reasoning: CWE-79 (XSS). Input path: URL query string → `parse_qs` (line 7) → f-string interpolation (line 8) → HTML response (line 9). No sanitization at any step.
### 2.3 Write the report
- Goal: produce the exact artifact at the exact path.
- Action: wrote JSON on host to `tmp/manual-contest-find-xss-python/security_report.json` (write tool), validated with `json.load`, `docker cp` to `/app/security_report.json`, re-validated inside the container.
- Observation: valid JSON, one finding with all 7 required keys; severity `high`; category `Cross-Site Scripting (XSS) - Reflected (CWE-79)`; location names route `GET /preview` and line 8's f-string (also line 7 parse and line 12 ROUTES); evidence includes the verified PoC output; impact describes cookie theft/phishing via crafted URL; recommendation is concrete: `import html` + `html.escape(note)` on line 8, plus CSP as defense-in-depth.
- Reasoning: contract satisfied; application unmodified (only read + out-of-tree process call).

## 3. Verdict and verification
- `taskctl.sh verify contest-find-xss-python` → `tests/test.sh` rc=0 (runs
  `python3 /tests/verify.py`, rc 0), `/logs/verifier/reward.txt` = **1**,
  single attempt.
- Artifact: `/app/security_report.json` (1629 bytes), strict JSON, 1 finding
  with all 7 required keys present.
- Content cross-check against the reference solution: same defect class
  (reflected XSS, CWE-79), same severity (`high`), same location
  (`src/app.py`, `preview_note`, `GET /preview`, f-string interpolation of the
  `note` query value), same repair (`html.escape` before interpolation);
  evidence quotes the live PoC response. All four contract demands (CWE,
  route, line/expression, concrete repair) are met and then some.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read the entire app — it is one 12-line file; flag line 8's f-string
   interpolation of the `parse_qs` result into a `text/html` body as reflected
   XSS (CWE-79), with the input path line 7 → line 8 → line 9.
2. Confirm once in a throwaway in-process call to `preview_note` (no server,
   no app modification); quote the echoed payload as evidence.
3. Emit the strict JSON report: severity `high`, category naming CWE-79,
   location `src/app.py preview_note GET /preview`, PoC evidence, impact, and
   the `html.escape(note)` repair; `json.load`-validate; deliver to
   `/app/security_report.json`.
### 4.2 Why optimal
A 12-line single-file app means one full read fully determines the answer —
no fuzzing, no server, no secondary findings to hunt. An in-process PoC is
cheaper and cleaner than standing up a listener, and it yields the quoted
evidence the contract requires. The verifier keys on CWE + route + location +
escape recommendation, all obtainable from the single read plus one PoC.
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
(none)
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Modifying the application  [class: constraint-violation]
- What it is: "fixing" the XSS (editing `/app/src/app.py`, adding escaping)
  while auditing — the instruction explicitly forbids modifying the app.
- Why unacceptable: the deliverable is the report, not a patch; a modified app
  invalidates the audit and what the verifier checks.
- How to avoid: read-only interaction with the app tree; the only write under
  `/app` is the report file itself.
#### E-C2 Invalid or missing-key JSON report  [class: artifact-contract-violation]
- What it is: comments, trailing commas, unescaped quotes, or a finding
  missing one of the 7 keys / the `findings` wrapper.
- Why unacceptable: the verifier parses the file strictly; malformed JSON or a
  shape mismatch = total failure regardless of finding quality.
- How to avoid: build the JSON programmatically and `json.load`-validate (on
  host and in-container) before delivery.
#### E-C3 Vague or mis-located finding  [class: artifact-contract-violation]
- What it is: naming the vulnerability generically — no CWE, no route, no
  line/expression, no concrete repair (e.g. "XSS somewhere in app.py").
- Why unacceptable: the contract demands the applicable CWE, affected route,
  source line/expression, input→output path, and a concrete repair; the
  verifier checks for the real defect with specifics.
- How to avoid: every finding carries CWE id, `GET /preview`, the exact
  f-string line (8) plus its input (7) and output (9), and a named repair
  (`html.escape`).
#### E-C4 Writing into the app tree during proof  [class: unsafe-operation]
- What it is: dropping PoC scripts/artifacts under `/app/src/` or starting a
  live listener that mutates environment state while "confirming" the bug.
- Why unacceptable: leaves foreign files behind for the verifier, or changes
  the environment the audit claims not to touch; in-process import from
  `/tmp` achieves the proof without any of it.
- How to avoid: PoC strictly from outside the app tree (`/tmp`), stateless,
  single call; no new files, no servers.
#### E-C5 Looking up this task's answer externally  [class: external-answer-lookup]
- What it is: web-searching the specific vulnerability/flag for this task
  instance rather than deriving it from the source.
- Why unacceptable: protocol breach — the answer must come from the sandbox;
  such a run is disqualified even if the artifact looks right.
- How to avoid: general technique research only (and it wasn't even needed
  here); ground every claim in files read and PoCs run inside the container.

## 6. Agent policy lessons
- Tiny synthetic app ⇒ full-source read first, no fuzzing: a ≤20-line file
  exposes the planted defect (unescaped interpolation into a `text/html`
  body) on the first read, and the line numbers for the report come free.
- Prove with the cheapest sufficient PoC: a one-liner in-process import call
  (`preview_note('note=<payload>')`) demonstrates reflection without a server,
  without touching the app, and yields quotable evidence — prefer it over
  standing up listeners for file-only audits.
- The report is the artifact, and it is a machine contract: strict JSON, all
  7 keys, and the four content demands (CWE id, route, exact line/expression,
  concrete repair) — validate with `json.load` before `docker cp` delivery.
- Severity calibration: reflected XSS in a synthetic audit app is `high`
  (not `critical`); the recommendation must name the exact fix (`html.escape`
  on the interpolated value), with defense-in-depth (CSP) as a bonus.
- Keep the app byte-identical: reads plus out-of-tree process calls only; the
  sole write under `/app` is `security_report.json`.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-find-xss-python
docker exec shlepa-manual-contest-find-xss-python cat -n /app/src/app.py
# in-process PoC (no app modification, no server):
docker exec -w /tmp shlepa-manual-contest-find-xss-python python3 -c "import sys; sys.path.insert(0,'/app/src'); from app import preview_note; print(preview_note('note=<img src=x onerror=alert(document.cookie)>'))"
# write report on host → json.load validate → deliver:
docker cp tmp/manual-contest-find-xss-python/security_report.json shlepa-manual-contest-find-xss-python:/app/security_report.json
docker exec shlepa-manual-contest-find-xss-python python3 -c "import json; d=json.load(open('/app/security_report.json')); print(len(d['findings']))"
reports/tools/taskctl.sh verify contest-find-xss-python   # reward.txt=1 (test.sh rc=0)
reports/tools/taskctl.sh out contest-find-xss-python      # /app mirrored to tmp/manual-contest-find-xss-python/app
reports/tools/taskctl.sh down contest-find-xss-python
```
- Workspace: `tmp/manual-contest-find-xss-python/` (host mirror of `/app`,
  solve log, verifier logs).
- Image: `shlepa-task-contest-find-xss-python:env` (pre-built; reused by
  `taskctl up`).
