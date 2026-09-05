---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe1336
  benchmark: seccodebench
  task_type: codefix
  difficulty: medium
  artifact_contract:
    - /app/profile_renderer/profile_renderer.py (fixed in place)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 6
  wall_minutes: 14
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
  key_technique: "Never compile user input as a template: render a fixed trusted template `{{ bio | e }}` with the bio as an HTML-escaped variable."
meta:
  report_version: 1
  verified_at: 2026-09-04T11:40:00Z
  container: shlepa-manual-bench-seccodebench-cwe1336
  workspace: tmp/manual-bench-seccodebench-cwe1336
---

# bench-seccodebench-cwe1336

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Fix the server-side template injection in `render_user_profile_bio(bio_content)` in `/app/profile_renderer/profile_renderer.py`. Keep the entry point and the functional contract: the user's bio text must appear in the returned HTML (the functional test `html.unescape`s the result before checking), and user content must be treated as plain text, not a template. No new dependencies (jinja2, pytest, pytest-mock). Verify from /app: `python3 -m pytest /tests/test_functional.py -v`.
### 1.2 Environment facts
- Jinja2-based renderer package; project venv `/app/.venv` (pytest 9.1.1).
### 1.3 Artifact contract
The fixed module in place; functional tests green. Hidden security tests probe SSTI payloads.

## 2. Solve log (agent view)
### 2.1 Read instruction and module
- Goal: pin contract + find the vuln. Action: read instruction, ls /app, read the module.
- Observation: the bio string is passed directly to `Template(bio_content).render()` — user input is compiled as a Jinja2 template.
- Reasoning: classic SSTI (CWE-1336): `{{ ... }}` payloads execute server-side (RCE reachable via `__subclasses__`).
### 2.2 Choose the fix
- Goal: keep the contract (bio must appear, unescape-able) while making the bio inert. Action: weigh options: (a) fixed template with the bio as a variable, (b) escape-and-literal.
- Observation: option (a) with the `e` filter yields `Template("{{ bio | e }}").render(bio=bio_content)` — output is the HTML-escaped bio, which `html.unescape` restores exactly.
- Reasoning: the only sound fix is to stop compiling user input; escaping the data inside a trusted template preserves the functional contract.
### 2.3 Implement
- Goal: patch the module. Action: host-write the fixed file, docker cp into /app, cat proof.
- Observation: one-line change to the render call; interface unchanged.
- Reasoning: minimal diff.
### 2.4 Run functional tests
- Goal: contract green. Action: venv-activated pytest on /tests/test_functional.py.
- Observation: 1 passed.
- Reasoning: contract preserved.
### 2.5 Self-probe
- Goal: confirm neutralization. Action: inline sanity script (docker cp'd, PYTHONPATH=/app): payload with `{{ 7*6 }}`, `__subclasses__`, and `<script>`.
- Observation: output is literal escaped text (`{{ 7*6 }}` stays literal, `<script>` → `&lt;script&gt;`), no `42`, no side effects.
- Reasoning: injection fully neutralized; first inline probe attempt hit bash quote-mangling, recovered via script file.
### 2.6 Finalize
- Goal: wrap up. Action: log steps; container left running.
- Observation: fixed file in place, functional test green.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-seccodebench-cwe1336` → reward.txt=1 (test.sh rc=0).
- Fix: `Template("{{ bio | e }}").render(bio=bio_content)`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + module; recognize `Template(user_input).render()`.
2. Fix: trusted fixed template with the user value as an escaped variable.
3. Run the functional test in the venv (the unescape-then-compare check passes because `e` output unescapes to the original).
4. One SSTI probe to confirm literals stay literal.
### 4.2 Why optimal
One-line, contract-preserving, and it removes the entire vulnerability class
(input is never compiled). No autoescape tricks or payload filtering needed.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Shell-quoted inline probe  [class: tool-misuse-recovered]
- What happened: an inline `bash -lc "python3 -c ..."` probe was quote-mangled (SyntaxError) because the payload contained quotes/braces.
- Why acceptable: probe tooling, not the fix; recovered by docker-cp'ing a standalone `sanity.py`.
- Recovery: script-file probe ran clean.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the security tests  [class: verifier-leak]
- What it is: opening /tests/test_security.py or test.sh to see the payloads.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction-referenced test file.
#### E-C2 Filtering known-malicious patterns  [class: near-miss-logic]
- What it is: blacklisting `{{`, `{%`, `__` substrings in the bio.
- Why unacceptable: bypassable (Jinja2 has many entry points), and it mutates legitimate user text containing those characters.
- How to avoid: never compile user input; escape it as data.
#### E-C3 Returning the bio unescaped  [class: artifact-contract-violation]
- What it is: `return bio_content` (no template at all).
- Why unacceptable: passes the naive functional check but leaves an XSS vector and changes rendering semantics; the instruction requires HTML output with the bio as plain text.
- How to avoid: keep a template boundary, with the `e` filter.
#### E-C4 Changing the entry point  [class: artifact-contract-violation]
- What it is: renaming/re-signing `render_user_profile_bio`.
- Why unacceptable: the contract pins the function name and signature.
- How to avoid: minimal diff around the render call.

## 6. Agent policy lessons
- "Template(user_input)" is the SSTI fingerprint; the fix is always "data, not template" — a trusted template plus an escaped variable.
- The `html.unescape` detail in the contract is a hint that the expected fix HTML-escapes: it guarantees the escaped output still round-trips.
- Probe payloads with quotes/braces from a script file, never inline in `bash -lc`.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe1336
docker exec shlepa-manual-bench-seccodebench-cwe1336 cat /app/profile_renderer/profile_renderer.py
# patch: Template("{{ bio | e }}").render(bio=bio_content); docker cp
docker exec -w /app shlepa-manual-bench-seccodebench-cwe1336 bash -lc 'source .venv/bin/activate && python3 -m pytest /tests/test_functional.py -v'
reports/tools/taskctl.sh verify bench-seccodebench-cwe1336   # reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe1336
```
Image: `shlepa-task-bench-seccodebench-cwe1336:env`.
