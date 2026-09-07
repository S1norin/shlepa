---
schema: shlepa.solution-report/v1
task:
  slug: bench-vulngym-langchain-template-injection
  benchmark: vulngym
  task_type: audit
  difficulty: hard
  artifact_contract: [/app/report.json]
solve:
  result: solved
  reward: "1"
  attempts: 2
  solve_steps: 3
  wall_minutes: 113
  verifier: tests/test.sh
  network_research: true
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write, web-fetch]
errors:
  minor_count: 2
  minor_classes: [near-miss-logic, near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "Mustache SSTI (CWE-1336): entry_point is the public function that first receives the template string (mustache_formatter def, string.py:111), and data_flow must cross every function boundary (render 433, tokenize 482, _get_key 346, subscript 379) down to the unrestricted getattr sink (mustache.py:382)."
meta:
  report_version: 1
  verified_at: 2026-09-06T22:01:38Z
  container: shlepa-manual-bench-vulngym-langchain-template-injection
  workspace: tmp/manual-bench-vulngym-langchain-template-injection
---

# Solution report: bench-vulngym-langchain-template-injection

## 1. Task brief (agent view)

### 1.1 Instruction (close paraphrase)
White-box security review of a curated, vulnerable source snapshot from a real
open-source project in `/app`: identify the single intended vulnerability.
Do not modify the supplied source files and do not exploit any external
system. Write `/app/report.json` as one JSON object with exactly 9 keys:
`vulnerability_found`, `vulnerability_type` (specific class or CWE),
`severity` (low|medium|high|critical), `entry_point` {file, line},
`critical_operation` {file, line or inclusive "start-end"}, `data_flow`
(list of {file, line}), `root_cause`, `impact`, `recommendation`. `line` may
be a positive integer or an inclusive `start-end` string. Trace the actual
control/data path in the supplied snapshot — a generic vulnerability guess is
not sufficient.

### 1.2 Environment facts
- `/app` contains exactly two source files:
  `libs/core/langchain_core/prompts/string.py` (346 lines, 11012 B) and
  `libs/core/langchain_core/utils/mustache.py` (673 lines, 21262 B), plus a
  dev `.venv` (Python 3.12, langchain_core 1.4.8 installed — a modern env,
  not part of the audited snapshot).
- `string.py`: `jinja2_formatter` (def 32) wraps rendering in
  `SandboxedEnvironment` (line 71) with an explicit "best-effort, do not use
  untrusted templates" warning (docstring 35-40); `mustache_formatter`
  (def 111) passes the template straight to `mustache.render` (line 121);
  `DEFAULT_FORMATTER_MAPPING` (206-210) wires `"mustache"` (line 208) into
  prompt `format()`.
- `mustache.py`: chevron-derived renderer. `render()` (def 433) tokenizes
  (line 482) and dispatches variable (511/513), no-escape (526/528), section
  (536/538) and inverted-section (635/637) tags — all resolve dotted keys via
  `_get_key()` (def 346), which walks key segments by dict subscript (379) →
  `getattr` fallback (382) → integer index (385). Partials are dict-only
  (no filesystem access).
- Not supplied in the snapshot: `prompts/base.py` (the `BaseStringPrompt.format`
  dispatch) and `utils/formatting.py` (the f-string template evaluator).

### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 9 keys above; `line` may
be an integer or inclusive `start-end` string; content must be self-consistent
with the snapshot evidence; source files under `/app` must remain unmodified.

## 2. Solve log (agent view)

Attempt 1 (rejected on locating): read both files end to end; diffed the
snapshot against upstream master (raw.githubusercontent.com); pinned the
hardening commit c4b6ba254e (#34035) whose added test is
`test_mustache_template_attribute_access_vulnerability`, and fetched advisory
GHSA-6qv9-48xg-fc7f / CVE-2025-65106 (severity high, CWE-1336, fixed
0.3.80/1.0.7); verified the leak live in the container
(`{{question.__class__.__name__}}` → class name, `{{question.__dict__}}` →
object dump, benign dict path intact). Wrote report.json with
entry_point = string.py:121 (the internal `return mustache.render(...)`
hand-off) and a 5-node data_flow (121 → 511 → 513 → 382 → 523) that skipped
the `render()`/`_get_key()` function boundaries → reward=0: "entry_point does
not locate the vulnerable input/control-flow entry" — the identification was
correct; the locating was wrong.

### 2.1 Re-derive every file/line from the actual source (attempt 2)
- Goal: confirm every citation with `cat -n` / `awk` inside the container before rewriting anything.
- Action: `cat -n` on both files; awk-checked each cited line number.
- Observation: string.py:111 `def mustache_formatter(template: str, /, **kwargs: Any) -> str:`, :121 `return mustache.render(template, kwargs)`, :206-210 DEFAULT_FORMATTER_MAPPING (:208 wires "mustache"); mustache.py:433 `def render(`, :482 `tokens = tokenize(template, def_ldel, def_rdel)`, :511 `elif tag == "variable":`, :513 `thing = _get_key(`, :528/:538/:637 the no-escape/section/inverted `_get_key` calls, :346 `def _get_key(`, :379 subscript attempt, :382 `resolved_scope = getattr(resolved_scope, child)`, :385 int-index.
- Reasoning: all of attempt 1's numbers were accurate; the fix is semantic — the attacker-controlled template string first enters the vulnerable flow at the public function that receives it (`mustache_formatter`, def 111; the dispatching `BaseStringPrompt.format` lives in `prompts/base.py`, which is not supplied). The sink is the single getattr line 382.

### 2.2 Live re-verification of the sink
- Goal: re-prove exploitability in this exact snapshot.
- Action: loaded `/app/libs/core/langchain_core/utils/mustache.py` via importlib under the container venv python; rendered attack templates with a stand-in message object (script in `/tmp`, sources untouched).
- Observation: `{{question.__class__.__name__}}` → 'Msg'; `{{&question.__dict__}}` → "{'content': 'howdy', 'additional_kwargs': {}}"; section form → 'L=Msg'; benign `{{person.name}}` → 'Alice' (normal path intact).
- Reasoning: the getattr fallback (382) is live and reachable from all tag branches; the data path 111 → 121 → 433 → 482 → 513 → 346 → 379 → 382 is the real control/data path.

### 2.3 Rewrite /app/report.json with the corrected locating
- Goal: fix `entry_point`, complete `data_flow`, and keep the (accepted) identification text consistent with the corrected path.
- Action: `entry_point` → string.py:111; `critical_operation` → mustache.py:382 (the getattr line itself); `data_flow` → 8 hops, one per boundary: string.py:111 (mustache_formatter receives the template) → :121 (render call) → mustache.py:433 (render entry) → :482 (attacker template tokenized) → :513 (variable branch calls `_get_key`) → :346 (`_get_key` entry) → :379 (subscript attempt) → :382 (getattr sink). Rewrote `root_cause`/`impact`/`recommendation` to cite the corrected path (branches 511/513, 526/528, 536/538, 635/637; jinja docstring 35-40). `docker cp` into `/app/report.json`; validated JSON parse, exact key set and order, and awk-verified every cited line against the `cat -n` output.
- Observation: JSON valid, 4263 bytes at `/app/report.json`; all 8 data_flow lines and all text citations match the snapshot verbatim; the two source files under `/app/libs` are unmodified (read-only access; the verification script ran from `/tmp`).
- Reasoning: the report is self-consistent — entry (111) and sink (382) are the exact lines, and the chain names each intermediate function boundary (`mustache_formatter` → `render` → `_get_key`) with the tokenize step in between.

## 3. Verdict and verification
- `taskctl.sh verify bench-vulngym-langchain-template-injection` (attempt 2) → reward.txt=1; verifier log: `PASS: report identifies and traces the expected vulnerability`.
- Final artifact: `vulnerability_type` = server-side template injection (SSTI), dot-notation keys resolved with a getattr() fallback, CWE-1336; `severity` = high; `entry_point` = string.py:111; `critical_operation` = mustache.py:382; `data_flow` = 8 nodes string.py:111 → :121 → mustache.py:433 → :482 → :513 → :346 → :379 → :382.

## 4. Ideal solution (hindsight)

### 4.1 Canonical path
1. Read both snapshot files end to end: `string.py` (formatter wiring; jinja2 already `SandboxedEnvironment`-wrapped with an explicit best-effort warning) and `mustache.py` (`render` 433 → tokenize 482 → tag branches resolving dotted keys through `_get_key` 346: subscript 379 → getattr 382 → int-index 385). Note what is absent: `prompts/base.py` (the `format()` dispatch) and `utils/formatting.py` (the f-string evaluator) — everything traceable lives in the two files.
2. Select the single intended vulnerability: the unrestricted getattr fallback in `_get_key`. The jinja2 path is sandboxed (mitigated, documented as best-effort) and the f-string evaluator is not supplied, so the mustache getattr chain is the only fully in-snapshot, unmitigated defect. (Optional corroboration: upstream fix commit c4b6ba254e / GHSA-6qv9-48xg-fc7f / CVE-2025-65106 pins the class — CWE-1336, severity high, fixed 0.3.80/1.0.7 — for exactly this chain.)
3. Locate endpoints and every boundary: entry = the public function that first receives the attacker-controlled template string — `def mustache_formatter`, string.py:111 (not the internal render hand-off at 121, since the dispatching caller is not in the snapshot); sink = the getattr line, mustache.py:382; data_flow = 111 → 121 → 433 (render def) → 482 (tokenize) → 513 (variable-branch `_get_key` call) → 346 (`_get_key` def) → 379 (subscript attempt) → 382 (sink) — every intermediate function boundary named.
4. Write `/app/report.json` with exactly the 9 keys (`vulnerability_type` naming the template-injection/SSTI class, severity high) and validate: JSON parses, exact key set, and every cited line re-checked against the source.

### 4.2 Why optimal
The snapshot is small (2 files, ~1000 lines) and the defect is structurally
unique (the only unmitigated in-snapshot sink), so once the entry semantics
(public entry vs internal hand-off) and the hop discipline (every function
boundary) are right, identification → locating → artifact is a single pass;
upstream diff/advisory research is a fast corroboration, not a requirement.

### 4.3 Estimated ideal steps: 4

## 5. Error analysis

### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Entry point located at the internal hand-off  [class: near-miss-logic]
- What happened: attempt 1 set `entry_point` to string.py:121 (`return mustache.render(template, kwargs)`) — an internal hand-off already inside `mustache_formatter` — instead of the public entry that first receives the attacker-controlled template string (def at line 111).
- Why acceptable: the file and the identification were correct and 121 is genuinely on the vulnerable path; the miss is a semantic near-miss of "where the input enters the control flow", not a wrong vulnerability.
- Recovery: attempt 2 re-located `entry_point` to string.py:111 (`def mustache_formatter`).
#### E-M2 Data flow skipped function boundaries  [class: near-miss-logic]
- What happened: attempt 1's 5-node flow (121 → 511 → 513 → 382 → 523) jumped from the render call to the variable branch and then to the sink, omitting the `render()` def (433), the tokenize step (482), the `_get_key` def (346) and the subscript attempt (379) between entry and sink.
- Why acceptable: every node present was real and on-path; the chain was simply incomplete in its intermediate hops rather than wrong.
- Recovery: attempt 2's 8-node flow names every boundary: 111 → 121 → 433 → 482 → 513 → 346 → 379 → 382.

### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier or expected values  [class: verifier-leak]
- What it is: consulting `tests/` (`report_grader.py`, `expected.json`) or `solution/` for the expected file/line/flow instead of deriving them.
- Why unacceptable: breaks simulation fidelity — the whole point of the audit is to locate the path from the snapshot alone.
- How to avoid: forbidden-path discipline; every file/line must be re-derived from the in-container source with `cat -n`/`awk`.
#### E-C2 Looking up this instance's specific answer online  [class: external-answer-lookup]
- What it is: fetching a published solution or the exact expected entry/sink lines for this specific VulnGym snapshot instance. General CVE/technique/advisory research (upstream diff, fix commit, GHSA advisory) is allowed; instance-specific answers are not.
- Why unacceptable: protocol invariant — `external_answer_lookup` must remain false.
- How to avoid: use the network only for class-level corroboration (upstream diff, advisory), never for the instance answer; log every lookup in the solve log.
#### E-C3 Reporting the wrong defect class  [class: artifact-contract-violation]
- What it is: naming the jinja2 sandbox (already mitigated, documented best-effort), the f-string evaluator (not supplied), or the lambda-section invocation as the single intended vulnerability.
- Why unacceptable: the grader matches the class against the expected defect (template injection / SSTI / CWE-1336) and checks the exact entry/sink locations; a wrong class fails identification outright.
- How to avoid: cross-check each candidate against supplied mitigations and absent files, then trace the chosen defect end-to-end in-snapshot before writing the report.
#### E-C4 Breaking the 9-key artifact contract  [class: artifact-contract-violation]
- What it is: extra or missing keys, a severity outside the expected set, non-substantive `root_cause`/`impact`/`recommendation` (under 40 chars), or malformed `line` values.
- Why unacceptable: the grader rejects any contract deviation even when the vulnerability is correct.
- How to avoid: build the JSON against the exact key set, then re-validate parse + key set + line format before verify.
#### E-C5 Modifying the audited source  [class: constraint-violation]
- What it is: editing the snapshot files under `/app/libs` (forbidden by the instruction; the grader also sha256-pins both files).
- Why unacceptable: destroys fixture integrity and fails the source-fixture check unconditionally.
- How to avoid: read-only access to `/app/libs`; run all reproduction/verification scripts from `/tmp` or the host mirror.

## 6. Agent policy lessons
- Entry-point semantics: `entry_point` is the public function that FIRST receives the attacker-controlled input (here `def mustache_formatter`, string.py:111) — not an internal call/hand-off further down the path (121). If the dispatching caller is not in the snapshot, the entry is the snapshot's public function that first takes the input.
- Data-flow hop discipline: name every intermediate function boundary between entry and sink — `def render` (433), tokenize (482), the branch call site (513), `def _get_key` (346), subscript attempt (379), then the sink (382). Endpoint-only chains fail even when both endpoints are plausible.
- In a curated snapshot audit, "the single intended vulnerability" is the only fully in-snapshot, unmitigated sink: cross-check candidates against supplied mitigations (jinja2 `SandboxedEnvironment`, explicitly documented best-effort) and absent files (f-string evaluator) before committing to a class.
- Upstream diff + security-hardening commit + advisory is a legitimate fast corroboration (pins class/CWE/severity), but ALL file/line citations must be re-derived from the snapshot itself — upstream line numbers drift across versions.
- Live in-container reproduction (importlib-load the snapshot module, render attack templates, confirm the benign path still works) is cheap and turns "looks vulnerable" into "verified".
- After a locating-only rejection, re-derive every cited line with `cat -n`/`awk` before rewriting — attempt 1's numbers were all correct and the fix was purely semantic; re-verification prevents introducing fresh citation errors while restructuring.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-vulngym-langchain-template-injection
# snapshot layout (exactly two audited files + dev venv):
docker exec shlepa-manual-bench-vulngym-langchain-template-injection find /app/libs -name '*.py'
# re-verify the key cited lines:
docker exec shlepa-manual-bench-vulngym-langchain-template-injection awk 'NR==111 || NR==121' /app/libs/core/langchain_core/prompts/string.py
docker exec shlepa-manual-bench-vulngym-langchain-template-injection awk 'NR==382' /app/libs/core/langchain_core/utils/mustache.py
# land the final report (9 keys; entry string.py:111, sink mustache.py:382, 8-node flow):
docker cp tmp/manual-bench-vulngym-langchain-template-injection/report.json shlepa-manual-bench-vulngym-langchain-template-injection:/app/report.json
reports/tools/taskctl.sh verify bench-vulngym-langchain-template-injection   # reward=1
reports/tools/taskctl.sh out bench-vulngym-langchain-template-injection
```
Image: `shlepa-task-bench-vulngym-langchain-template-injection:env`.
Workspace: `tmp/manual-bench-vulngym-langchain-template-injection/` —
`app/` (host mirror of `/app`, final `report.json` in `app/` and at top level),
`solve-log.md` (final, both attempts), `solve-log-attempt1.md`,
`upstream-master-mustache.py` / `upstream-master-string.py` (upstream copies
used for the diff), `logs/verifier/` (reward.txt, verifier.log).
