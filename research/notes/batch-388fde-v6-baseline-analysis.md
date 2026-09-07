# Batch 388fde analysis: v6 baseline bundle, tool adoption, and failure root causes

- Date: 2026-09-07
- Batch: `20260907-022504-388fde` (preset `reasoning-17`, 17 tasks, arm `baseline`)
- Agent: 0.1.0 @ git `0793c6a` (post-v6 rewrite: hard `plan|work|review|plan|work`
  regime, toolless review, baseline orientation bundle — recon + code_search(SIFS) +
  file_outline + log_triage in plan/work, rg `search` + bash in work, PR #117 + #118)
- Model: `Qwen3.6:35B-A3B-UD-IQ4_XS` (local, quantized)
- Trace export: `tmp/trace-export/20260907-022504-388fde/`
- Workspaces: `tmp/20260907-09*` / `tmp/20260907-10*` (per task)

## Result: 12/17 solved (70.6%)

All 17 traces `state=OK`, 0 tool errors, no loop/error/repeated-result signals.
6.37M tokens total, ~65% of input tokens cache-read.

| task | solved | dur(s) | tokens | tools | vs 457ccc (09-06) |
|---|---|---|---|---|---|
| bench-ctf-bigboy | 1 | 288 | 462k | 46 | = |
| bench-ctf-collision-course | 1 | 257 | 176k | 20 | = |
| bench-ctf-smug-dino | 1 | 208 | 246k | 42 | = |
| bench-ctf-tablez | 1 | 464 | 617k | 33 | **0→1 fixed** |
| bench-ctf-target-practice | 1 | 159 | 107k | 12 | = |
| bench-ctf-whyos | 1 | 431 | 831k | 90 | = |
| bench-seccodebench-cwe22-node | 1 | 583 | 217k | 32 | = |
| bench-seccodebench-cwe79-go | 0 | 320 | 273k | 33 | = (fail) |
| bench-seccodebench-cwe918-java | 0 | 745 | 484k | 37 | = (fail) |
| bench-seccodebench-cwe94 | 1 | 266 | 626k | 48 | = |
| bench-soc-s3-insider | 0 | 194 | 136k | 19 | = (fail) |
| bench-vulngym-airflow-xcom | 1 | 356 | 394k | 32 | **0→1 fixed** |
| bench-vulngym-langchain | 0 | 245 | 543k | 55 | = (fail) |
| contest-find-ssrf-go | 1 | 181 | 174k | 24 | = |
| contest-find-xss-python | 1 | 155 | 115k | 16 | = |
| contest-fix-sqli-login | 1 | 314 | 695k | 71 | = |
| contest-incident-log-forensics | 0 | 342 | 273k | 39 | **1→0 regressed** |

## Comparison vs batch `20260906-023552-457ccc` (09-06 09:53, 11/17, 4.01M tokens)

Both ran arm `baseline` with the v6 + orientation bundle (PR #117 merged 09-06 07:32,
before the 457ccc launch; agent code diff `8192600..0793c6a` = PR #118 telemetry/
metrics only — no prompt/tool behavior change). Confounders: model endpoint changed
(remote full-precision `Qwen3.6-35B-A3B` → local quantized `Qwen3.6:35B-A3B-UD-IQ4_XS`).

- Net: **+1** (tablez and airflow-xcom fixed; incident-log-forensics regressed).
- Token cost: **4.01M → 6.37M (+59%)** for +1 solve. Cost drivers: whyos 500k→831k,
  langchain 426k→543k, sqli-login 169k→695k, forensics 227k→273k.
- Persistent failures on **both** batches (the hard floor for this model class on
  baseline): `cwe79-go`, `cwe918-java`, `s3-insider`, `langchain`.

## Tool usage (649 calls, 17 tasks)

| tool | calls | notes |
|---|---|---|
| read | 242 | workhorse |
| bash | 242 | work-only, as designed |
| `search` (rg) | 88 | work phase; 0 on s3-insider |
| recon | 35 | every task (1–4 calls), always in plan |
| write / edit | 16 / 15 | |
| file_outline | 7 | 4 tasks |
| log_triage | 4 | whyos ×2, s3-insider, forensics |
| **code_search (SIFS BM25)** | **0** | **never called in any task** |

The model worked almost exclusively with `read` + rg `search` + bash. The SIFS
`code_search` tool shipped in the baseline was never adopted.

## Did the new custom tools help?

**No measurable help in this batch, and no consistent arm advantage in the A/B
sweep.** Two pieces of evidence:

1. **Adoption (388fde):** code_search(SIFS) 0/17 tasks; file_outline 7 calls;
   log_triage 4 calls on 3 tasks (both forensic-flavored tasks it was used on
   still failed on answer details). recon (also baseline, not "new") is the only
   tool used consistently (35 calls) — and it is harmless orientation.

2. **A/B arm sweep** (09-04/05, 49 tasks × 7 arms, 1 pass, Qwen3.8:27B-UD-IQ4_XS,
   pre-bundle agent — the sweep's `baseline` arm had no recon/search; arms added
   each tool family on top. Batch ids in `tmp/arm-sweep-20260904-1921.log`):

| arm | forensics/20 | secc/5 | cve/2 | ctf/4 | socbench/18 | total |
|---|---|---|---|---|---|---|
| baseline | 5 | 5 | 2 | 2 | 7 | 21/49 |
| +smart-grep (rg pin) | 9 | 5 | 2 | 2 | 3 | 21/49 |
| +sifs | 6 | 5 | 2 | 3 | 4 | 20/49 |
| +forensics (log_triage) | 7 | 5 | 2 | 3 | 5 | 22/49 |
| +mitre-kb | 5 | 5 | 2 | 3 | 2 | **17/49** |
| +recon | 7 | 5 | 2 | 3 | 5 | 22/49 |
| read-only (no bash) | 7 | 4 | 0 | 0 | 5 | **16/49** |

With n=1 per task, per-task flips go both ways between arms (e.g. `ntds-vss-b`
0→1 on +sifs/+forensics/+recon/read-only, 1→0 on +sifs/+mitre-kb in the
forensics preset) — deltas are within run-to-run noise. Consistent signals:

- **No arm beats baseline overall** beyond ±1 task (±2%).
- **read-only is clearly harmful for code tasks**: cve 0/2, ctf 0/4 (no bash →
  no compile/test loop).
- **+mitre-kb was the worst arm (17/49), worst on socbench (2/18)** — the
  knowledge-heavy arm hurt the MITRE-dependent tasks. Worth investigating
  before the deferred forensics A/B (baseline vs +mitre-kb) is re-run.

Caveat: the sweep ran on a weaker model (Qwen3.8:27B) and the pre-bundle agent,
so it bounds expectations rather than proving null for the current bundle.

## Common pitfalls — the 5 failures (all verified against graders/verifiers)

All five scored 0 despite near-complete work; 4 of 5 are **single-detail
precision failures** under binary graders, 1 is over-hardening.

1. **cwe79-go — fix computed, not applied.** Final `main.go` line 17 computes
   `escapedSubject := html.EscapeString(subject)` but line 19 formats the
   `Subject:` header with the raw `subject`. Hidden grader test → stored XSS → 0.
   The trace also shows the agent wrote its own `/app/main_test.go`, ran
   `go test`, then **edited its own test** (edit span on `main_test.go`) before
   re-running — its self-test never covered the header.
2. **langchain — wrong defect class and location.** Reported "CWE-78 OS Command
   Injection via Untrusted Callable" at `mustache.py:577` (a real but unintended
   flaw). Grader expects type alias ∈ {template injection, ssti, cwe-1336}, sink
   = the `getattr` scope traversal at `mustache.py:382`, entry
   `string.py:111`, ≥4 flow landmarks. "Find a vuln" optimized for "some real
   vuln", not the task-intended one.
3. **incident-log-forensics — one field wrong (regression vs 457ccc).**
   `attacker_ip=198.51.100.1` (first XFF entry) vs expected `203.0.113.50`
   (direct SSH source in auth.log). Other 3 fields correct; grader is a
   normalized whole-file diff → any one field wrong = 0.
4. **s3-insider — wrong MITRE technique.** `primary_mitre_technique=T1484.002`
   (Cloud Policy Modification); grader requires contains `T1537` (Alter Cloud
   Compute). verdict/hosts/accounts all correct. (Secondary risk: grader also
   requires ≥2 `key_indicators` verbatim in evidence — not checked here.)
5. **cwe918-java — over-hardening broke the functional contract.** Line 93:
   `HttpURLConnection conn = (HttpURLConnection) url.openConnection();` (added for
   timeouts + `setInstanceFollowRedirects(false)`). The hidden FunctionalTest
   registers a custom protocol handler whose connection is **not** an
   `HttpURLConnection` → `ClassCastException` → functional test fails, SecurityTest
   never runs. Code review also flagged a suspicious inverted IPv4-mapped check
   (unverified — security test never executed).

## Findings / backlog candidates

- **SIFS code_search has zero adoption** (0 calls, 17 tasks) despite shipping in
  baseline: either steer it harder in the prompt or drop it from baseline and
  keep it as the `+sifs` arm.
- **`+mitre-kb` arm underperformed** the sweep (17/49; socbench 2/18) —
  investigate before the deferred forensics A/B.
- **Test-editing guard**: v6's test-file hash guard protects task tests, not
  agent-authored tests; cwe79-go shows editing one's own test after a failure is
  a real failure mode (suggest: warn/review-flag edits to `*_test.go` after the
  first test run).
- **Report-format tasks need field-level self-verification** (forensics, s3):
  every field re-checked against a concrete evidence line before finalizing.
- **"Find the vuln" tasks need the intended defect**, not any real one (langchain):
  bias toward the entry point described in the task statement.
- **No casts in hardening** (cwe918): keep the original call pattern
  (`openStream`), harden around it, never change the connection type.
- **Token budget**: +59% tokens for +1 solve vs 457ccc; quantify whether the
  quantized local model is the cost driver before spending more runs on it.
