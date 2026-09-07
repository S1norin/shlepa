# Encouraging SIFS adoption + fixing the 4 persistent pitfalls

- Date: 2026-09-07
- Source: batch `20260907-022504-388fde` analysis
  (`research/notes/batch-388fde-v6-baseline-analysis.md`), the 09-04/05 arm
  sweep, the 09-06 tool-steering A/B (`research/notes/one-shot-tool-steering.md`),
  web research below
- Status: proposal — concrete prompt/guard changes with draft text, to be
  implemented as small PRs and A/B-tested per the validation plan at the end

## SIFS `code_search`: 0/649 calls — why, and what to try

**Observed:** in 388fde the model used `search` (rg) 88 times and `code_search`
(SIFS BM25) **zero times in 17 tasks**. v3-corpus history: code_search 2/98
runs. Steering text already exists (base.md ORIENTATION TOOLS, plan.md step 4,
work.md exploration list) — it is ignored.

**Why (evidence):**
1. **Tool redundancy / familiar-tool prior.** Baseline ships *two* search tools
   with overlapping descriptions ("search for code"). External work on tool
   selection consistently reports that similar tools cause confusion and the
   model picks the familiar one (rg/grep is the strongest prior a code model
   has). Our own A/B (09-06) confirms: steering reliably drives the **plan**
   phase (partly by bash absence), but **work-phase tool choice did not move**
   and one-shot examples had no consistent effect (n=5, rejected).
2. **What the A/B DID show works:** plan-phase behavior follows the scripted
   tool order (recon → triage → search → read) — enforcement-by-absence and a
   mandatory ordered script are the two demonstrated levers at this model
   scale (Qwen3.6/3.8, 27-35B quantized).
3. **External (supports, not decisive — frontier models):** few-shot tool-call
   examples lift selection recall 16%→52% (LangChain, 3 examples as chat
   messages > system string); Anthropic tool-use examples 72%→90% (1–5
   realistic examples, only where non-obvious); arXiv 2509.18076: structured
   function-calling templates give 3–12% relative error reduction vs free-form
   CoT. Our 09-06 A/B already tested the few-shot lever and found no gain at
   n=5 — do **not** re-test one-shots; use the demonstrated levers.

**Interventions, cheapest first:**

| # | change | where | lever |
|---|--------|-------|-------|
| S1 | **De-overlap the two tools**: `search` = exact literal strings/file names only ("you already know the text"); `code_search` = default first call for any "where is X / how does Y work" question. Rewrite the two bullets in base.md ORIENTATION TOOLS + the matching lines in work.md. | prompts | positioning |
| S2 | **Mandatory first call**: in plan.md step 4, code-fix and vuln-discovery tasks: "your FIRST orientation call must be code_search (one query built from the task's key terms), then read the returned files; `search` only for exact literals it missed." | prompts | ordered script (demonstrated lever) |
| S3 | **Negative example** (Comet: sparing negatives set boundaries): in work.md exploration list: "Do not start code exploration with `search` (grep) or bash grep — code_search first, grep only to confirm exact strings." | prompts | boundary-setting |
| S4 | **Ordering**: list `code_search` before `search` in every tool list (base.md PHASE TOOLS, plan.md, work.md). | prompts | cheap |
| S5 | **Absence enforcement (fallback if S1–S4 still show ~0):** remove `search` from the PLAN toolset (plan keeps code_search + file_outline + read + recon + log_triage). Plan is read-only; exact-grep in plan is a small loss, forced SIFS use in plan is guaranteed. This is the demonstrated mechanism (plan already follows tool absence). | toolsets.py + prompts | structural |
| S6 | **System-driven pre-fetch (bigger fallback):** runner auto-runs SIFS with task-derived keywords for code tasks and injects top hits into the plan context. Adoption problem disappears entirely; cost = ~200–500 tokens/plan when useful. | runner.py | structural |

If S1–S4 (one prompt PR) still yields ~0 adoption, ship S5 with it; S6 is the
last resort. If adoption still fails, the honest conclusion is to drop
code_search from the baseline zip (keep the `+sifs` arm) — a dead tool costs
prompt tokens and zip budget for nothing.

## The 4 persistent pitfalls — concrete fixes

All four fail binary graders on a single detail; all four already have a
neighboring rule in the prompts that was insufficient. Each fix below is a
**reinforcement of an existing block**, not a new section.

### P1. `cwe918-java` — over-hardening broke the functional contract

Fact: the cast `(HttpURLConnection) url.openConnection()` was added for
timeouts + redirect control. **`setConnectTimeout`/`setReadTimeout` exist on
the base `URLConnection` class** — no cast needed for timeouts at all; only
`setInstanceFollowRedirects` is HTTP-specific and must be `instanceof`-guarded.
The grader's FunctionalTest registers a custom protocol handler whose
connection is not an `HttpURLConnection` → CCE → security test never ran.

Existing block: base.md "CODE FIX TASKS" → "Keep the API surface unchanged".
Missing: *behavioral* surface (expression types).

**Fix (base.md CODE FIX TASKS, add 2 bullets):**
```
- Harden AROUND existing calls, never replace them: keep the original
  expression and the type it produces. Never cast an existing connection,
  stream, or client object to a narrower type — the verifier may use custom
  handlers whose objects are not that type. Prefer the base-class API where
  one exists (e.g. connect/read timeouts are on the base connection class,
  no cast needed); guard type-specific calls with an instanceof check.
- The verifier runs functional tests alongside the security tests: anything
  that makes the original program behave differently on normal input is a
  failure, even if the security property now holds.
```

### P2. `cwe79-go` — fix computed but not applied + agent edited its own test

Two distinct failure modes:
(a) `escapedSubject` computed, raw `subject` still used in the `Subject:`
header — classic "fix written, not wired".
(b) Agent **wrote its own** `/app/main_test.go`, ran `go test`, then **edited
the test** to make it pass — its test never covered the header. This is the
"tampering" category from the reward-hacking literature (arXiv 2605.02964:
"the agent modifies evaluation-relevant code or state to change what is being
measured"). The v6 test-file hash guard protects **task-provided** tests only.

Existing block: base.md "CODE FIX TASKS" → "Run the provided tests until
green. Do not modify tests unless the task explicitly says to." — the agent
arguably followed this (its test was not "the provided tests").

**Fix A — prompt (base.md CODE FIX TASKS, replace the tests bullet):**
```
- Run the provided tests until green. Do not modify provided tests unless
  the task explicitly says to. If you write your own test: it must check the
  task's stated acceptance behavior (every output field/value the task
  names), and you may NEVER edit a test to make a failing run pass — fix the
  code instead. If a test of yours is simply wrong, delete it and write a
  better one; say so in the summary.
- After a fix, prove the vulnerable pattern is gone: search for the old
  expression and expect zero hits, and verify against the task's acceptance
  behavior — not against your own test alone.
```

**Fix B — mechanical guard (runner.py, small code change):** track
agent-created files matching test patterns (`*_test.go`, `test_*.py`,
`*_test.py`, `conftest.py`, `tests/**`); after the first test command runs in
the task, block `edit`/`write` to those files (return a refusal message:
"test files are locked after the first test run — fix the code, not the
test"). The runner already sees every tool call; this is bookkeeping.
Alternative (weaker): inject the fact into the review relay ("you edited your
own test after a failure — re-verify against the task spec").

### P3. `s3-insider` + `incident-log-forensics` — wrong single field (T1484.002 vs
T1537; XFF IP vs SSH source IP)

Both are the same class: **selection precision under a whole-file-diff
grader**. Note work.md already carries "COMPARE 2+ before any selection" and
SELF-VALIDATE — and s3-insider still failed. So the rule either wasn't
followed or its output wasn't checked. The gap: the comparison is
in-model-only, nothing forces the *rejected candidate* to be recorded, and
the toolless review relay never re-derives selected fields.

**Fix (two prompt edits):**
1. base.md REASONING DISCIPLINE #4 (COMPARE 2+) — make the comparison
   *recorded*:
   ```
   4. COMPARE 2+ before any selection (technique, host, account,
      vulnerability, fix): list at least 2 candidates, state for each why it
      fits and why it doesn't, and pick the one that explains ALL
      observations — not just one. RECORD the rejected candidate and the
      specific evidence line that killed it, in the deliverable's
      rationale/indicators where the format allows. A selection with no
      recorded rival is not done.
   ```
2. review.md — add a rule (review has no tools but sees the full transcript
   with evidence):
   ```
   - FIELD CHECK (report-style deliverables only): re-derive each selected
     field (technique, IP, host, account, flag) from the evidence quoted in
     the transcript. Flag any field whose quoted evidence would equally
     support a rival candidate — put it in problems with the rival named.
   ```

Optional, family-scoped (overfitting risk — keep as a follow-up only if the
generic fixes don't move these tasks): for DIGITAL FORENSICS, "the attacker
IP is the source IP of the initial-access event (auth log), not a
proxy/X-Forwarded-For entry, unless the task defines the field otherwise";
for SOC, "when several techniques fit, the primary is the one causing the
impact (exfil, compute created, persistence), not the enabling step."

### P4. `langchain` — wrong defect class and location

Model reported CWE-78 at mustache.py:577 (a real but unintended flaw);
grader wants the SSTI/CWE-1336 path (getattr traversal at :382 from entry
string.py:111, ≥4 flow landmarks). The literature pattern (IRIS, arXiv
2405.17238; taint-spec extraction, 2601.10865): LLMs are far better at
**confirming a hypothesized flaw along a named path** than at open
discovery; the working structure is hypothesis (entry + primitive) →
dataflow trace with file:line per hop → report the *flow*, not the sink.

**Fix (base.md, new VULNERABILITY DISCOVERY block mirroring CODE FIX TASKS):**
```
VULNERABILITY DISCOVERY
- Follow the feature the task names. Trace it from its public entry point to
  the sink and report THAT path's defect as a dataflow chain: entry → … →
  sink, file:line for every hop (aim for 4+ landmarks). The task asks for
  the flaw of the named feature, not "some real flaw in the repo".
- If you find a genuine flaw on a different path, record it as secondary —
  never as the answer.
- CWE: pick the most specific CWE for the exact primitive (eval/exec,
  getattr-cast, shell=True, ...) and name the primitive in the report. When
  two CWEs are possible, say which and why.
```
Plus plan.md step 1: for vuln tasks the deliverable spec must include "the
named feature/entry point" extracted from the instruction (the plan already
extracts artifact specs; this extends it).

## Sequencing and validation

1. **PR 1 (prompt-only bundle):** S1–S4 + P1 + P2-A + P3 (both edits) + P4
   (base.md block + plan.md extension). Pure prompt diff, no behavior code.
2. **PR 2 (mechanical):** P2-B test-file lock in runner.py (small, unit-testable).
3. **Validation (A/B, existing infra):** run the 5 failing tasks
   (cwe79-go, cwe918-java, s3-insider, langchain, incident-log-forensics)
   3× each, before and after the bundle (per-task preset, as in
   `experiments/ab-readonly.yaml`); success = solved in ≥1/3 on ≥3 of the 5
   without regressing the 12 solved (spot-check tablez + airflow-xcom).
   SIFS metric: `code_search` > 0 in ≥50% of tasks (vs 0/17 now).
   If SIFS still ~0 → ship S5 (drop `search` from plan) in PR 3 and re-run.
4. **Do NOT re-run the +mitre-kb arm yet** — it was the worst sweep arm
   (17/49, socbench 2/18); understand why the KB prefix hurt before adding
   any MITRE knowledge to the baseline.

## Sources

- Local: `research/notes/batch-388fde-v6-baseline-analysis.md`,
  `research/notes/one-shot-tool-steering.md`, arm-sweep log
  `tmp/arm-sweep-20260904-1921.log`, current prompts
  (`agent/shlepa_agent/prompts/{base,plan,work,review}.md`).
- Web: LangChain "few-shot prompting to improve tool-calling performance"
  (2024); Anthropic "advanced tool use" (2025); Comet "few-shot prompting"
  (2026); arXiv 2509.18076 (structured templates for function calling);
  arXiv 2605.02964 (reward-hacking benchmark — tampering category);
  arXiv 2405.17238 (IRIS, LLM-assisted taint/spec analysis); arXiv 2601.10865
  (multi-agent taint-spec extraction); arXiv 2502.02337 (SIEM→ATT&CK
  mapping); tool-overload reports (achan2013, gethackteam, 2025–2026);
  Java `URLConnection` base-class timeout API (docs.oracle.com).
