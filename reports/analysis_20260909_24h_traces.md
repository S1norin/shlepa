# 24h trace analysis (2026-09-08 20:05 → 2026-09-09 14:33)

Scope: 15 dev batches, 223 scored runs (+1 smoke) on the `baseline` toolset.
Metrics: all MLflow run metrics (tokens, per-phase, solved) for every run.
Full traces: exported for 6 batches (134 runs, still exporting); failure
modes below are verified against those traces plus the verifiers in
`tasks/*/tests/` — C1/C2 signatures confirmed in all 6 exported batches.
Comparison baseline: `reports/summary.md` (35 manual solves, 5.3 avg steps,
7.1 h), `reports/analysis_qwen36.md` (earlier failure classes), and
`research/notes/batch-bf0ef6-failures.md` (per-failure deep dive of the 27B
batch, whose findings are folded into C1–C3 below).

## Headline numbers

| metric | value |
|---|---|
| runs (14 full batches × 17 tasks) | 221 (64.3% solved, 141/221) |
| models | Qwen3.6-35B-A3B: 204 runs (63.7% solved); Qwen3.6-27B-UD-IQ4_XS: 18 runs (72.2% solved, n small) |
| total input tokens | 55.4M (81.1% cache-read → ~10.5M effectively new) |
| phase split | work 62.2%, plan 21.7%, commit 16.2% |
| avg duration | ~240 s/task (manual baseline: ~14 min/task incl. verification) |
| cache rate by phase | work 88.1%, plan 80.7%, **commit 54.6%** |
| multi-cycle runs (2+ plan→work) | 9/83 sampled (11%) |

## What the agent does well

1. **Stable solving on well-specified tasks.** 6 tasks solved 13/13:
   collision-course, smug-dino, target-practice, cwe94, find-ssrf-go,
   find-xss-python. Near-stable: fix-sqli-login 12/13, incident-log-forensics
   12/13, cwe22-node 11/13. Efficient wins are cheap: xss 73K,
   target-practice 68K, collision 118K input tokens (manual: 3–6 steps).
2. **Strong evidence handling on SOC.** On s3-insider (0/13) the report was
   correct on verdict, hosts, accounts, and verbatim indicators in sampled
   runs — only the MITRE ID missed. The failure is one field, not the analysis.
3. **Genuine forensics work, not loop spin.** whyos's "100× bash loop" signal
   is 91 *unique* commands (deb extraction, dylib strings, console.log mining)
   across two cycles. It is search breadth, not a degenerate loop.
4. **Code-fix quality is high.** The cwe918-java fix (0/13) is a well-structured
   SSRF hardening: scheme/whitespace/credential rejection, full IP-class
   validation, IPv4-mapped-IPv6 handling, redirect-hop validation. It fails on
   exactly one robustness detail (below).
5. **Cache discipline in work/plan** (80–88%): conversations are stable
   prefixes; context peaks stay small (25–51K) even in 2M-token runs.

## Why the agent fails — six classes

### C1. Exact-line / exact-field precision (vulngym, tablez) — 5 of 6 zero/low tasks
The graders demand zero-tolerance coordinates (file:line, landmark coverage,
one MITRE ID). Sampled misses, all one detail off:
- **langchain (0/13):** right files read (string.py, mustache.py), but reports
  "CWE-94 code injection" at string.py:32/44 instead of SSTI at
  string.py:111 → mustache.py:382. The `getattr(resolved_scope, child)` at
  mustache.py:382 is the intended critical operation; the agent never commits
  to it. Decision failure, not search failure.
- **airflow-xcom (1/13):** sampled report had correct type, entry (line 83),
  critical span — but data_flow covered 83/86/87 and missed landmark line 84.
  One missing landmark = fail.
- **s3-insider (0/13):** verdict/hosts/accounts/indicators all correct;
  answered T1530, grader requires T1537. Same MITRE-granularity class as the
  manual run's 15 retries (T1548.005→T1078.004, T1626→T1078.004, …) — the
  human's first attempts failed identically.
- **tablez (3/12):** approach 100% correct (objdump .data table inversion,
  preimage decode, re-feed verification). Sampled wrong flag
  `flag{alfle_l00l_kups_ar3_b3tter_f0m_3}` vs `flag{t4ble_l33t_…}` — partial
  table corruption (some chars map right, `b3tter` survives, `table`→`alfle`),
  i.e. an off-by-N in table extraction. Verification caught it, but the run
  had no budget left to retry.

### C2. Defensive-coding gap (cwe918-java, 0/13 — every batch)
The fix does `(HttpURLConnection) url.openConnection()`. The FunctionalTest
harness installs a `URLStreamHandlerFactory` returning a plain
`URLConnection`, so the cast ClassCastExceptions → public preview returns
"Error…" → functional test fails. The reference solution (`solution/solve.sh`)
uses `if (c instanceof HttpURLConnection)`. Same miss in all 13 batches: the
model never writes a cast without an `instanceof` guard, even though the
instruction says "preserve ordinary public URL preview behavior".

### C3. Time-budget exhaustion with a read-only commit (whyos 7/13, bigboy 8/13)
Regime caps: plan 80 s / work 120 s / review 60 s, **no token budget**.
- whyos: manual solve = 8 steps ("the Preferences process logged the typed
  token verbatim"). The agent broad-searches (426 candidate 32-hex strings),
  exhausts the 120 s work cap without writing `flag.txt`, commit returns
  `next_round`, a second (sometimes third) cycle repeats it. Top-10 token runs
  are whyos (9 of 10); one run: 92 LLM calls, 146 tool calls, 2.06M input
  tokens, and it *solved* — the budget is spent re-doing the same search with
  a longer horizon. Failed runs are the same search that never finishes.
- bigboy (sampled d02f82 failure): work ended with no answer; the **read-only**
  commit phase then did the disassembly (objdump rodata, found the candidate
  in `boi.asm`) and could not write it. The run's last LLM call died mid-
  verification (see §Telemetry). No deliverable on disk → reward 0.
- tablez (bf0ef6): after the wrong-flag verification, a 55.5 s LLM call was
  cut by the work cap, then a 30 s toolless `final_ask` and the review's first
  call each burned their entire caps with **zero output** — the 27B model's
  thinking stalls (55–60 s per call) outgrow the phase windows, and the
  terminal review has no retry/fallback: a recoverable run died on one slow call.

### C4. Early terminations without a verdict
Sampled cwe79-go (d02f82, 84 s, 15 calls) and bigboy (d02f82) traces end
mid-tool-call with no commit verdict and no `shlepa.termination_reason` tag,
while MLflow reports FINISHED with longer wall time (172 s / 317 s vs trace
84 s / 242 s). Trailing spans are being lost in the OTel export, so these
failures are currently un-diagnosable from traces. Needs a runner-side
termination tag on every end path (see §Telemetry).

### C5. Model-level noise on medium tasks
bigboy/cwe79-go failures are spread across 5 different batches each with low
token counts (76–226K) — consistent with early aborts (C4) or one-shot misses
rather than a systematic task misunderstanding.

### C6. (Carried over) SOC indicator-format discipline
`reports/analysis_qwen36.md` classes (double-escaped paths, ticket labels
instead of zeek leaves, verdict flips) recur in the manual-run retry log; the
s3-insider sampled runs show the indicator side is now mostly fine — the
residual SOC gap is MITRE selection (C1).

## Where to cut tokens (55.4M per 24 h window)

| lever | est. saving / window | risk |
|---|---|---|
| **whyos search strategy** — prompt-level: "identify who wrote the secret, mine *their* process log first; cap candidate enumeration". Manual took 8 steps; agent uses both 120 s work caps on breadth. | ~5–6M (22% of total; whyos = 12M of 55M) | none — keeps solving, halves cost |
| **Cap or hard-timeout the 0-solve tasks** (langchain 5.1M, cwe918 2.7M, s3-insider 1.8M at ~300–400K avg): a per-task token/time ceiling would stop paying 2 full cycles for answers that never land. | ~9M at 0 solve-rate today | converts to savings only while unsolved; revisit after C1/C2 fixes |
| **Commit-phase cache loss** — first commit call re-bills the whole work context (sampled: 23.3K in at 0% cache right after work at 99% cached; phase avg 54.6% vs work 88.1%). Fix the prefix break (trim shape) or eviction window. | ~3–4M effectively-new tokens + prefill latency | none |
| **Trim the plan phase** — 21.7% of all tokens (54K avg/run) for tasks whose manual solution is 5 steps. Plan does recon+outline+reads that work repeats. A leaner plan (recon + outline, ~20K) is the cheapest global cut. | ~10–15% of total (~7M) | low — keep plan for multi-step tasks only |
| **Multi-cycle overhead** — 9/83 sampled runs ran 2–3 cycles; each next_round re-bills a fresh plan+work conversation. The cycle is what turned whyos into a 2M-token run. Cutting cycle count (via C3 fix) is the same lever as the whyos line. | included above | low |

## Where to spend more

1. **cwe918-java: one robustness rule.** A single prompt constraint —
   "guard every downcast: `instanceof` before cast; code must survive
   non-HTTP connection objects" — is worth the full 2.6M/batch back. This is
   the highest ROI change in the report: 13/13 runs are 95% correct.
2. **MITRE selection (SOC + vulngym):** the `+mitre-kb` arm exists
   (`toolsets.py`, pinned v19.2 KB, ~8K tool output) but **no batch in the
   window used it** (all `baseline`). A one-shot arm run on the 17-task set
   would directly test the T1530-vs-T1537 class. Cheapest experiment
   available.
3. **Audit-task prompt nudge: source vs sink.** Both vulngym failures traced
   the *wrong side* of the flow (airflow: the Jinja pusher template instead of
   the bash_command sink; langchain: the invocation of the resolved callable
   instead of the `getattr` key resolution). A prompt line distinguishing
   entry point (where untrusted input enters) from critical operation (the
   sink that consumes it) targets both at once.
4. **Verify-then-retry budget for decode tasks (tablez, whyos):** the agent
   verifies (re-feed into binary) and then runs out of budget. Give the work
   phase an explicit "if your self-check fails, you have one fix iteration"
   norm — or bump WORK_CAP for tasks whose deliverable is a computed value.
   Sampled evidence: bb708a's tablez solved on cycle 2 (303K) while bf0e's
   died on cycle 1 (115K).
5. **Commit must be able to finish, not just judge.** bigboy's answer was
   found in commit; commit is read-only. Either (a) let commit write the
   deliverable when work computed it, or (b) make `next_round` the default
   when the deliverable is absent, with a guaranteed second work cycle
   (currently the second cycle exists, but the first commit can die mid-check
   and consume its whole 60 s cap doing work-phase labor).
6. **Spend on plan quality, not volume, for forensics.** whyos's plan phase
   (307K in the 2M run) produced no discriminator ("mine console.log"). The
   manual solver's plan was one sentence: the flag is what the Preferences
   process logged. A plan that must name the *writer* of the secret before
   work starts would cut cycles.

## Telemetry gaps found while analyzing

1. **Trailing spans lost in OTel export** — MLflow `duration_sec` exceeds the
   trace root span for bigboy (317 s vs 242 s), cwe79 (172 s vs 84 s); last
   spans lack usage attributes. C4 failures are invisible to trace analysis
   until this is fixed (export flush on process exit / span batch delay).
2. **`shlepa.termination_reason` only on the timeout path** — one tagged run
   in 83 sampled (whyos bb708a); every other non-clean end is untagged.
   Tag every end path (llm_error, budget_abort, no_verdict).
3. **Loop signals are count-based artifacts** — "bash ×100 (≥4 in 6-call
   window)" fires on normal forensic work (91 unique commands). Suggest
   hashing arguments and requiring repetition of the *same* command.
4. Manifest `solved`/`tokens` are null (fields not populated by
   trace-export); MLflow metrics were used instead.

## Open items

- Background trace export of the remaining 9 batches is still running
  (`/tmp/export_rest.log`). C1/C2 are confirmed in every exported batch so
  far; C3/C4 samples are concentrated in the already-exported set.
- 27B-UD-IQ4_XS (12/17 + 1/1) vs 35B-A3B (63.7%): n=1 batch; worth a
  controlled arm comparison before any model switch.
