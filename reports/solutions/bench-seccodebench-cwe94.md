---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe94
  benchmark: seccodebench
  task_type: codefix
  difficulty: hard
  artifact_contract:
    - /app/workflow_transformer/workflow_transformer.py (fixed in place)
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 7
  wall_minutes: 11
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, file-write, pytest]
errors:
  minor_count: 2
  minor_classes: [tool-misuse-recovered, near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 5
  key_technique: "Replace eval() with an allowlist AST interpreter (ast.parse mode='eval' + recursive evaluator) covering exactly the documented expression language; everything else raises ValueError before execution."
meta:
  report_version: 1
  verified_at: 2026-09-04T11:40:00Z
  container: shlepa-manual-bench-seccodebench-cwe94
  workspace: tmp/manual-bench-seccodebench-cwe94
---

# bench-seccodebench-cwe94

## 1. Task brief
### 1.1 Instruction (close paraphrase)
Fix the code injection in `transform_step_data(transform_map_expr, input_data)`
in `/app/workflow_transformer/workflow_transformer.py`. A valid expression is a
Python dict literal whose values use: literals; lookups of string keys on
`input_data` (keys may contain any characters, e.g. `input_data['__class__']`);
arithmetic (`+ - * / // %`), unary minus; comparisons (incl. chained);
boolean `and`/`or`. Anything outside that language (calls, attribute access,
other names, non-`input_data` subscripts, comprehensions, …) must be rejected
with `ValueError`/`TypeError` and must not execute any code. Keep the entry
point and behavior for valid expressions. Verify from /app: `python3 -m pytest
/tests/test_functional.py -v`.
### 1.2 Environment facts
- Package used by a workflow automation tool; project venv `/app/.venv`
  (pytest 9.1.1).
### 1.3 Artifact contract
The fixed module in place; functional tests (4) green. Hidden security tests probe code-injection payloads.

## 2. Solve log (agent view)
### 2.1 Read instruction and module
- Goal: pin contract + find the vuln. Action: read instruction, ls /app, read the module.
- Observation: `eval(transform_map_expr)` on caller-controlled input in module globals — `__import__('os').system('id')` or `input_data.__class__` would execute.
- Reasoning: CWE-94; the fix must be an interpreter for the documented sub-language, not `eval` with a restricted `__builtins__` (sandbox escapes are well known).
### 2.2 Design the allowlist grammar
- Goal: enumerate exactly what must work and what must die. Action: from the instruction: dict literals (no `**`), str/num/bool/None literals, the single name `input_data`, string-key subscripts (chainable, any-char keys), `+ - * / // %` and unary `+ -` (excluding `**` — DoS guard), comparisons incl. chaining, `and/or` (+ `not` with short-circuit semantics), parentheses, plus a node/depth cap.
- Observation: malformed syntax must also be rejected cleanly.
- Reasoning: `ast.parse(mode="eval")` gives a typed tree; a recursive evaluator that knows only the allowed node types is the interpreter.
### 2.3 Implement the AST interpreter
- Goal: write the evaluator. Action: recursive function over `ast` nodes — `Dict` (literals only for keys), `Constant`, `Name` (only `input_data`), `Subscript` (only on a resolved `input_data` lookup, only string-literal slices, chainable), `BinOp`/`UnaryOp`/`Compare`/`BoolOp` whitelisted operators, `Paren` via the natural tree; everything else → `ValueError`; `ast.parse` failure → `ValueError`; non-str input → `TypeError`; 100-node depth cap.
- Observation: host-written file docker-cp'd to /app; cat proof matches.
- Reasoning: rejection happens during evaluation, before any code runs.
### 2.4 Run functional tests
- Goal: contract green. Action: venv-activated pytest (4 tests: basic, safe expressions, complex safe expressions, injection-resistant fields).
- Observation: first run on system python failed (no pytest) → venv; then 4 passed.
- Reasoning: the documented language works end-to-end.
### 2.5 Injection self-probes
- Goal: confirm nothing outside the language executes. Action: 17 payloads (`__import__('os')`, attribute access, `input_data.__class__`, lambda, comprehension, f-string, `**`, deep nesting, …).
- Observation: all rejected with ValueError/TypeError, no side effects; one probe artifact (`{'a': {'x': 1}}`) looked like a miss but is a legitimate nested dict literal.
- Reasoning: the allowlist is closed.
### 2.6 Finalize
- Goal: wrap up. Action: log steps; container left running.
- Observation: fix in place, 4/4 green.
- Reasoning: done.
### 2.7 (merged) — no further iteration needed.
- Goal/Action/Observation/Reasoning: single-pass success after the venv fix.

## 3. Verdict and verification
- `taskctl.sh verify bench-seccodebench-cwe94` → reward.txt=1 (test.sh rc=0).
- Fix: strict allowlist AST interpreter; `eval` removed entirely.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + module; recognize bare `eval` on input.
2. Extract the exact allowed sub-language from the instruction (it is the spec).
3. Write the AST allowlist interpreter (parse `mode="eval"`, recursive evaluator, whitelist node+operator types, reject-before-execute, depth cap).
4. Run the 4 functional tests in the venv.
5. Self-probe a payload set covering every banned construct.
### 4.2 Why optimal
`eval`-with-restricted-globals is not a fix (known escapes: attribute
chains, dunders, comprehensions). A closed AST interpreter is the only
construction that matches "must not execute any code" by design.
### 4.3 Estimated ideal steps: 5

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 System python instead of project venv  [class: tool-misuse-recovered]
- What happened: first pytest run failed with `No module named pytest` (system python).
- Why acceptable: environment discovery; recovered with `/app/.venv/bin/python` (3.12.13).
- Recovery: 4/4 passed.
#### E-M2 False alarm on a legitimate nested dict  [class: near-miss-logic]
- What happened: a probe of `{'a': {'x': 1}}` was briefly read as a rejected case.
- Why acceptable: nested dict literals are in the documented language; re-reading the spec resolved it — no code change needed.
- Recovery: n/a.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the security tests  [class: verifier-leak]
- What it is: opening /tests/test_security.py or test.sh to see the payload list.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction-referenced test file.
#### E-C2 "Safe" eval with restricted builtins  [class: near-miss-logic]
- What it is: `eval(expr, {"__builtins__": {}})` or a restricted globals dict.
- Why unacceptable: attribute access, dunder chains, comprehensions, and other AST features still execute; it is not a security boundary.
- How to avoid: a closed AST interpreter; unknown node ⇒ reject.
#### E-C3 Forgetting to reject before executing  [class: functionality-broken]
- What it is: an evaluator that partially executes a node before deciding it is disallowed (e.g. evaluating a call's arguments).
- Why unacceptable: the contract says rejected expressions "must not execute any code"; partial evaluation leaks side effects.
- How to avoid: validate the entire tree (or short-circuit at the first disallowed node before touching it) — structure check first, then evaluate.
#### E-C4 Over-restricting the documented language  [class: artifact-contract-violation]
- What it is: rejecting legitimate constructs (chained comparisons, `not`, string keys with special characters, unary plus).
- Why unacceptable: functional tests cover the documented language; missing a construct fails the contract.
- How to avoid: implement exactly the spec list, then run all 4 functional tests.

## 6. Agent policy lessons
- When the instruction specifies an expression language, it is the grammar spec — transcribe it into node/operator whitelists before writing code.
- "Must not execute any code" ⇒ structure-validate the whole expression, then evaluate; never interleave execution with discovery.
- Excluding `**` (exponentiation) is a deliberate DoS guard (e.g. `9**9**9**9`); such limits are expected, not bugs.
- The 4 functional tests in this image already probe the safe-language corners (injection-resistant fields, complex safe expressions) — they double as the language test suite.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe94
docker exec shlepa-manual-bench-seccodebench-cwe94 cat /app/workflow_transformer/workflow_transformer.py
# patch: allowlist AST interpreter (no eval); docker cp
docker exec -w /app shlepa-manual-bench-seccodebench-cwe94 bash -lc 'source .venv/bin/activate && python3 -m pytest /tests/test_functional.py -v'
reports/tools/taskctl.sh verify bench-seccodebench-cwe94   # reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe94
```
Image: `shlepa-task-bench-seccodebench-cwe94:env`.
