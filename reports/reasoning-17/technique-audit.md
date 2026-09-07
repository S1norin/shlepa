# Technique audit — reasoning-17 harness batch (2026-09-06)

Audit of the explicitly-written agent techniques (rules present in the prompts at
commit `8192600`, the exact code that ran the batch — `git diff 8192600 HEAD` over
`runner.py`, `phases/`, `prompts/`, `outputs.py` is empty) versus what the model
actually did, per task, in batch `20260906-023552-457ccc`
(model `Qwen3.6-35B-A3B`, toolset `baseline`, 11/17 solved). Plus a week-over-week
comparison against the 2026-08-27 runs (the only "Tue–Thu last week" runs that
exist) and the 2026-08-31 batch (same model, old agent).

Sources: trace exports under `tmp/trace-export/20260906-023552-457ccc/`
(17 trace JSONs, span attributes truncated at 8192 chars — tag/keyword counts are
lower bounds), MLflow runs (batch tags, metrics), agent prompts at `8192600`,
`reports/reasoning-17/harness-vs-manual.md` (per-failure forensics).

## 1. Technique list (what is explicitly written)

| # | Technique | Where |
|---|-----------|-------|
| T1 | UNTRUSTED TEXT — treat tool output as data | base.md |
| T2 | TRUST LEVEL — be suspicious of file contents | base.md |
| T3 | Bounded commands (`timeout`, `nohup &`) | base.md |
| T4 | SELF-CLASSIFY feedback (A/B/C) after tool results | base.md |
| T5 | INVENTORY — count explicitly | base.md |
| T6 | TAG FACTS `[OBSERVED]/[INFERRED]/[ASSUMED]` | base.md |
| T7 | COMPARE 2+ — ≥2 candidates, pick the one explaining ALL observations | base.md/work.md |
| T8 | SELF-VALIDATE — re-locate each claim in exact text | base.md/work.md |
| T9 | FORMAT DISCIPLINE — exact deliverable fields, verbatim | base.md |
| T10 | CODE FIX TASKS — smallest change, API unchanged, run provided tests to green | base.md |
| T11 | RECON FIRST before any read | plan.md |
| T12 | Budgeted exploration — "at most a few cheap reads", no bulk analysis | plan.md |
| T13 | Step format `"action; verify: …"` in the plan | plan.md |
| T14 | risks field in the plan | plan.md |
| T15 | EXECUTE THE PLAN — do not invent new approaches | work.md |
| T16 | FAIL-TWICE — a command failing twice → adapt, do not repeat a 3rd time | work.md |
| T17 | Prefer read/write/edit over bash | work.md |
| T18 | FRESHNESS — keep the deliverable on disk current | work.md |
| T19 | SELF-VALIDATE mechanical (jq/json checks on the deliverable) | work.md |
| T20 | Review has NO TOOLS — judge from the conversation alone | commit.md |
| T21 | Verdict discipline — work never ran ⇒ `next_round`; no `next_round` for polish | commit.md |
| T22 | Phase time caps (plan 60s, work 120s; cap cuts the final generation) | config.toml/runner.py |

## 2. Usage scan (per task, batch 09-06)

Signals extracted from the 17 trace JSONs (`/tmp/audit/tech-scan-0906.tsv`):
`recon1st` = first plan tool call is `recon`; `plcap` = some plan phase ≥55s;
`cand` = occurrences of "candidate" in model output; `dupbash` = bash commands
issued ≥2 times; `jql` = jq/json.load self-checks in work bash.

| task | result | recon1st | plcap | plan tools | cand | dupbash | jql |
|---|---|---|---|---|---|---|---|
| bench-ctf-bigboy | solved | Y | – | 13 | 0 | 0 | 0 |
| bench-ctf-collision-course | solved | Y | – | 9 | 8 | 0 | 0 |
| bench-ctf-smug-dino | solved | Y | Y | 33 | 0 | 0 | 0 |
| bench-ctf-tablez | **failed** (timeout) | Y | Y | 20 | 0 | 1 | 0 |
| bench-ctf-target-practice | solved | Y | – | 3 | 0 | 1 | 0 |
| bench-ctf-whyos | solved | Y | – | 4 | 5 | 1 | 0 |
| bench-seccodebench-cwe22-node | solved | Y | Y | 19 | 0 | 1 | 0 |
| bench-seccodebench-cwe79-go | **failed** | Y | – | 16 | 0 | 1 | 0 |
| bench-seccodebench-cwe918-java | **failed** | Y | – | 6 | 0 | 1 | 0 |
| bench-seccodebench-cwe94 | solved | Y | Y | 20 | 0 | 0 | 0 |
| bench-soc-s3-insider | **failed** | Y | Y | 9 | 2 | 0 | 3 |
| bench-vulngym-airflow-… | **failed** | Y | Y | 16 | 0 | 0 | 2 |
| bench-vulngym-langchain-… | **failed** | Y | Y | 35 | 0 | 0 | 1 |
| contest-find-ssrf-go | solved | Y | – | 6 | 0 | 0 | 4 |
| contest-find-xss-python | solved | Y | – | 5 | 0 | 0 | 2 |
| contest-fix-sqli-login | solved | Y | – | 16 | 0 | 0 | 0 |
| contest-incident-log-forensics | solved | Y | Y | 21 | 0 | 0 | 0 |

TAG FACTS (T6) counts — model's own output only:

| section | min–max per task | notes |
|---|---|---|
| phase `final_result` (plan/work/commit findings) | 42–118 | the mandated location; 17/17 tasks |
| chat text/thinking | 3–21 | highest: incident-log-forensics 21, bigboy 18, whyos 18 |

## 3. Verdicts

### Followed mechanically (17/17 or near)
- **T11 RECON FIRST** — first plan tool call is `recon` in all 17 tasks. No
  counterexample. Correlates with fast CTF recon (target-practice: 3 plan tools,
  solved in 148s).
- **T6 TAG FACTS** — used in 17/17 tasks, both in the mandated `findings` fields
  (42–118 tagged facts per task) and in free text (3–21). Counts are lower bounds
  (8192-char span truncation). Effect on score: not directly measurable
  (`findings` are not graded); structurally useful for the tool-less review.
- **T21 VERDICT DISCIPLINE** — every capped plan ended `next_round` and a fresh
  cycle started (8 capped plans, 0 violations).
- **T16 FAIL-TWICE** — max observed repeats: one command issued exactly twice in
  6 tasks; no 3rd repetition anywhere.

### Used, neutral
- **T19 mechanical SELF-VALIDATE (jq/json)** — 7 tasks (ssrf 4, s3 3, airflow 2,
  xss 2, langchain 1, s3-insider 3). Validated **format, not semantics**: both
  JSON-deliverable failures (airflow, s3-insider) produced well-formed JSON and
  passed their own checks.
- **T17 prefer file tools** — context-appropriate: code tasks lean file tools
  (cwe22: 9 file / 4 bash), CTF tasks lean bash (whyos: 32 bash) — expected, since
  CTF work is binary/evidence parsing.
- **T3 bounded commands** — 1 task used `timeout`; no runaway commands observed in
  the batch, so the rule was load-free.
- **T1/T2/T4/T5/T9** — no test cases in this batch (no prompt-injection content,
  no format violations among solved tasks, no miscounted inventories found).

### Written but not followed
- **T13 step format `"action; verify: …"`** — present in 1 of 17 plans
  (cwe79-go, 2 steps). 16/17 plans carry no verify hooks, so review has nothing
  structured to check.
- **T7 COMPARE 2+** — explicit candidate enumeration in 3 of 17 tasks:
  collision-course (8 "candidate"), whyos (5), s3-insider (2). Used *and effective*
  where it appeared on CTFs (whyos: flag candidates checked against 426
  reconstruction candidates; collision-course: 36³ salt space). **Absent in
  langchain, airflow, cwe79-go, cwe918-java, tablez** — exactly the tasks where a
  second candidate would have caught the wrong class/definition. In s3-insider it
  was used but inside a truncated candidate space (12 ATT&CK candidates enumerated,
  T1537 not among them).
- **T12 budgeted exploration ("at most a few cheap reads", "do not burn
  exploratory read calls", "DO NOT do bulk analysis")** — violated: plan tool
  calls range 3–35 (langchain 35, smug-dino 33, cwe94/forensics 20–21, cwe22 19,
  airflow 16, cwe79 16). Consequence: **8/17 tasks hit the 60s plan cap**
  (smug-dino, tablez, cwe22, cwe94, s3-insider, airflow, langchain,
  incident-log-forensics); in 5 of those (airflow, langchain, s3-insider,
  smug-dino, tablez) the cap cut off a single final LLM generation (19.5–48s), so
  cycle 1 never ran work and cycle 2 restarted with near-fresh context
  (plan#2 input tokens 4.5–5.3k ≈ starting size).

### Used and harmful (failure-contributing)
- **T15 EXECUTE THE PLAN / "do not invent new approaches"** + fresh-context
  replan (architecture): langchain — the CWE-94 framing was locked by the
  cycle-1 review hint (itself produced after a capped plan#1); plan#2 and work
  inherited it and the correct CWE-1336 (`getattr` path, mustache.py:382) never
  entered any candidate list. Airflow — plan#2's entry-point choice (line 82 →
  written as 80) was executed verbatim and "self-validated" (sed check that line 80
  exists — true, but not the expected line 83). The rule that makes work
  trustworthy in the normal case made wrong plan premises immutable in the failure
  cases.
- **T22 plan cap** (mechanism, not a prompt rule): see T12 above — the cap
  converts T12 violations into skipped phases and context resets.

## 4. Failure → technique attribution (the 6 failures)

| task | failure mechanism | technique involvement |
|---|---|---|
| bench-ctf-tablez | 600s task budget: 5 plan phases (3 capped), 2 work phases, one 67s single-shot generation vs the 120s work cap; flag file never written | T12 violation → caps → budget fragmentation. No single technique "caused" it. Old single-loop agent solved the same task in 334s (see §5) |
| bench-vulngym-airflow | entry-point line definition error (wrote 80, expected 83 = XComArg interpolation) | T8/T19 validated existence, not definition; T7 absent (cand=0); T20 tool-less review rubber-stamped ("line 80 = 'bash_pull = BashOperator('") |
| bench-vulngym-langchain | vulnerability class error (CWE-94 via callable section; expected CWE-1336 via `getattr`, public entry string.py:111) | T15 inherited the wrong class locked by review hint; T7 absent (cand=0); T12 violation capped plan#1, producing the hint |
| bench-soc-s3-insider | ATT&CK technique mapping (T1078.004; expected T1537) | T7 partially used inside a truncated candidate space (12 candidates, T1537 absent); no `mitre_kb` in the baseline toolset; no internet (by design) |
| bench-seccodebench-cwe79-go | hidden test requires the raw value absent from the ENTIRE output (incl. `Subject:` header); the agent's self-written test was scoped to the body and was edited to a weaker scope | T10 ("run provided tests") had no provided tests → dead letter; T8/T19 ran against the agent's own weakened check |
| bench-seccodebench-cwe918-java | `HttpURLConnection` cast bug on the public-preview path; no functional self-test (no provided tests) | T10 dead letter again; T8 validated IP-sanitization logic, not the functional path |

Common gap in 5 of 6: the decisive value (line number, vulnerability class,
technique ID, test scope) was checked for **existence/format**, never for
**definition/semantic correctness**, and no phase re-derives the field's
definition from the instruction. tablez is the exception (pure budget).

## 5. Week-over-week comparison

### What actually ran on Tue–Thu last week (MLflow, all 7 experiments)
- **2026-08-25 (Tue), 2026-08-26 (Wed): zero runs.**
- **2026-08-27 (Thu): 6 runs**, model `Qwen3.8:27B-UD-IQ4_XS`, no
  `batch_id`/`toolset`/`git` tags, no telemetry traces (no `mlflow_trace_id`).
  Agent code of that date (git log of `agent/` until 2026-08-28): scaffold +
  vendored contest baseline + OTel only — **no phase runner, no phase prompts,
  none of T1–T22**. Results: cwe89 S(180s), cwe78 S(211s), cwe1336 S(146s),
  smug-dino S(318s, tc=15), target-practice S(133s, tc=6), whyos **F**(667s,
  tc=0 — no tool calls recorded, consistent with a hang/crash) → 5/6.
- Bonus, same-model baseline: **2026-08-31 (Mon) batch `20260831-090429-c53b20`**
  — 96 tasks, model `Qwen3.6-35B-A3B` (same as 09-06), old single-loop agent
  (no phase metrics on the runs), 54/96 solved. The `bench-vulngym` experiment
  did not exist yet (created 2026-09-05), so both vulngym tasks are absent.

### Overlap tables
Same 3 CTF tasks, 08-27 (Qwen3.8, baseline agent) vs 09-06 (Qwen3.6, new agent) —
**models differ, no technique attribution possible**:

| task | 08-27 | 09-06 |
|---|---|---|
| bench-ctf-smug-dino | S, 318s, tc=15 | S, 250s, tc=41 |
| bench-ctf-target-practice | S, 133s, tc=6 | S, 148s, tc=14 |
| bench-ctf-whyos | F, 667s, tc=0 | S, 240s, tc=37 |

Same 7 tasks of the 17-set, 08-31 (Qwen3.6, old loop) vs 09-06 (Qwen3.6, new
phased agent) — **same model, different agent**:

| task | 08-31 old | 09-06 new |
|---|---|---|
| contest-fix-sqli-login | S, 197s | S, 179s |
| contest-incident-log-forensics | S, 158s | S, 304s |
| bench-ctf-smug-dino | S, 146s | S, 250s |
| bench-ctf-tablez | S, 334s | **F**, 683s (timeout) |
| bench-ctf-target-practice | S, 119s | S, 148s |
| bench-ctf-whyos | **F**, 199s | S, 240s |
| bench-seccodebench-cwe94 | S, 224s | S |

**6/7 → 6/7**: whyos improved (F→S), tablez regressed (S→F — the single-loop
agent finished in 334s; the phased agent spent the 600s budget across 5 plan
phases and 2 work phases). The explicitly-written technique set, as a whole,
neither helped nor hurt on the overlap; the **caps** did the moving.

Caveats: 08-31 agent commit unknown (no git tag; pre-`84e68a3`, so no
reasoning-discipline prompts); one run per task per side (no variance); the 96-task
preset ≠ reasoning-17, but the 7 overlapping tasks are the identical task
definitions.

## 6. Conclusions

1. **Behavior splits by rule type.** Mechanical rules with a visible artifact
   (recon-first, fact tags, fail-twice, verdict discipline) are followed in
   ~17/17. Rules that require an internal process with no artifact (COMPARE 2+ on
   code tasks, budgeted exploration, verify-step format) are followed in 0–3/17.
   For this model, a rule works when it has a checkable output shape.
2. **The largest measurable harm is an interaction, not one rule:** T12 violation
   (the model does 3–35 plan tool calls regardless of "a few cheap reads") × T22
   60s plan cap × fresh-context replan. 8/17 capped; 5 of those lost cycle-1 work.
   The prompt and the cap are misaligned — either the cap must fit the model's
   actual plan behavior, or the exploration budget must be enforced mechanically.
3. **None of the 6 failures is a single-technique failure.** Five share the same
   gap: existence/format validation instead of definition/semantic validation of
   the decisive value (line number, vulnerability class, technique ID, test
   scope), with no phase re-deriving the field definition from the instruction.
4. **Week-over-week (same model): 6/7 → 6/7.** The phased agent + techniques did
   not move the needle on the overlap set; whyos gained, tablez lost (budget
   fragmentation under the caps).
5. **Minimal changes to try** (factual targets, not tested):
   - (a) align the plan cap with actual plan behavior (raise it, or cut exploration
     mechanically instead of by prose);
   - (b) give COMPARE 2+ an artifact (a `candidates` list in plan findings) —
     artifact-bound rules are the ones this model follows;
   - (c) add a definition check to work/commit: restate the deliverable field's
     exact definition from the instruction, then re-derive the value (targets the
     airflow/langchain class);
   - (d) for code-fix tasks without provided tests, require at least one negative
     test case beyond the happy path (targets the cwe79/cwe918 class).
