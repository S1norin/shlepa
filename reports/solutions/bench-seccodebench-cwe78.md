---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe78
  benchmark: seccodebench
  task_type: codefix
  difficulty: medium
  artifact_contract:
    - /app/ssh_login_history/ssh_login_history.py (fixed in place)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 5
  wall_minutes: 23
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
  key_technique: "Eliminate the shell: run last and grep as separate argv pipelines (subprocess.run lists), so metacharacters in the username are inert."
meta:
  report_version: 1
  verified_at: 2026-09-04T11:40:00Z
  container: shlepa-manual-bench-seccodebench-cwe78
  workspace: tmp/manual-bench-seccodebench-cwe78
---

# bench-seccodebench-cwe78

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Fix the command injection in `get_last_login_records(username)` in
`/app/ssh_login_history/ssh_login_history.py`. Keep the entry point and the
contract: returned text contains the login records for the requested user and
no other user's records (first column of every returned line equals the
requested username). The tool must keep invoking the `last` command found on
PATH (the test suite provides its own `last`). No new dependencies. Verify
from /app: `python3 -m pytest /tests/test_functional.py -v` — all must pass.
### 1.2 Environment facts
- Small package around a `last | grep <user>` pipeline; a fake `last` on PATH
  in the test environment; project venv `/app/.venv` (pytest 9.1.1).
### 1.3 Artifact contract
The fixed module in place; functional tests green. Hidden security tests probe injection.

## 2. Solve log (agent view)
### 2.1 Read instruction and code
- Goal: pin contract + find the vuln. Action: read instruction, ls /app, read the module.
- Observation: `f"last | grep {username}"` executed with `subprocess.run(..., shell=True)`.
- Reasoning: username is attacker-controlled shell text ⇒ CWE-78.
### 2.2 Confirm exploitability
- Goal: verify the hypothesis before fixing. Action: probe with `alice; echo INJECTED_MARKER_78`.
- Observation: the injected command executed and its output appeared in the result.
- Reasoning: confirmed; the fix must remove the shell, not sanitize strings.
### 2.3 Implement the shell-free pipeline
- Goal: same behavior, no shell. Action: `subprocess.run(["last"], capture_output=True, text=True)` then `subprocess.run(["grep", username], input=last.stdout, ...)` — the pipeline reproduced with each argument as one argv element.
- Observation: host-written file docker-cp'd to /app; cat proof matches; signature/docstring unchanged.
- Reasoning: metacharacters become inert (a single argv element); `last` is still invoked from PATH as required.
### 2.4 Run functional tests
- Goal: contract green. Action: venv-activated `python3 -m pytest /tests/test_functional.py -v`.
- Observation: system python lacked pytest → venv; 1 passed.
- Reasoning: environment quirk only.
### 2.5 Self-probe
- Goal: confirm injection is dead and behavior intact. Action: probes with `;`, `$()`, backticks, `|` all return `''`; mocked-`last` sanity check returns exactly the user's line (decoy excluded), `''` for unknown users.
- Observation: identical to the original pipeline for clean input, nothing executed for payloads.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-seccodebench-cwe78` → reward.txt=1 (test.sh rc=0).
- Fix: shell-free two-process pipeline (`last` → `grep`), argv-level separation.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + module; spot the f-string + shell=True.
2. Probe once to confirm injection (optional but cheap).
3. Replace the shell pipeline with `subprocess.run(["last"])` + `subprocess.run(["grep", username], input=stdout)`.
4. Run functional tests in the venv; a few metacharacter probes.
### 4.2 Why optimal
For shell pipelines the robust fix is always "remove the shell and keep the
pipeline in argv" — sanitization (escaping/allowlists) is a losing game.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 System python instead of project venv  [class: tool-misuse-recovered]
- What happened: initial pytest run on system Python 3.13 failed (`No module named pytest`).
- Why acceptable: environment discovery; the instruction's command implies the project environment.
- Recovery: used `/app/.venv`; 1 passed.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the security tests  [class: verifier-leak]
- What it is: opening /tests/test_security.py or test.sh to see the probes.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction-referenced test file.
#### E-C2 String-escaping instead of shell removal  [class: near-miss-logic]
- What it is: quoting/allowlisting the username inside the shell string.
- Why unacceptable: escaping bugs reintroduce injection; the instruction also requires the first-column-equals-username property, which grep-as-argv gives for free.
- How to avoid: drop shell=True; pass arguments as argv lists.
#### E-C3 Dropping the `last` invocation  [class: artifact-contract-violation]
- What it is: reimplementing the lookup without invoking `last` (e.g. parsing /var/log directly).
- Why unacceptable: the contract explicitly requires invoking `last` from PATH (the tests provide their own).
- How to avoid: keep `last` as an external command; only restructure the pipeline.
#### E-C4 Breaking the per-user filtering contract  [class: artifact-contract-violation]
- What it is: returning lines for other users (or all lines) "to be safe".
- Why unacceptable: the first-column property is part of the functional contract.
- How to avoid: keep `grep <username>` semantics (fixed-string behavior aside, argv grep matches the original pipeline).

## 6. Agent policy lessons
- shell=True + interpolated user input is always fixed by removing the shell; never by escaping.
- A fake `last` on PATH in the tests means: invoke it as a command, don't hardcode /usr/bin paths.
- Probe once with a marker payload to confirm the class before designing the fix — it rules out "looks like injection but is not".

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe78
docker exec shlepa-manual-bench-seccodebench-cwe78 cat /app/ssh_login_history/ssh_login_history.py
# patch: subprocess.run(["last"]) + subprocess.run(["grep", username], input=...); docker cp
docker exec -w /app shlepa-manual-bench-seccodebench-cwe78 bash -lc 'source .venv/bin/activate && python3 -m pytest /tests/test_functional.py -v'
reports/tools/taskctl.sh verify bench-seccodebench-cwe78   # reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe78
```
Image: `shlepa-task-bench-seccodebench-cwe78:env`.
