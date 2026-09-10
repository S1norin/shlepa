# Web research: solutions for the 24h trace report (2026-09-10)

- **Category:** research (web research, 2025–2026 sources only — no pre-2025 papers used as primary basis)
- **Source:** web search (SearXNG) + direct source fetches, 2026-09-10
- **For:** `reports/analysis_20260909_24h_traces.md` — six failure classes (C1–C6), token levers, telemetry gaps
- **Scope:** what current (2025–2026) practice says about each class, plus the concrete fix proposed for this repo. C2 is flagged honestly as "no new research needed."

---

## C1 — Exact-line / exact-field precision (vulngym langchain/airflow, s3-insider MITRE, tablez)

### What current research says

- **RepoAudit (ICML 2025, open-sourced, github.com/PurCL/RepoAudit)** — the current reference
  point for LLM code-audit agents. Its core idea: the model does **not** get to assert
  coordinates it hasn't checked. It tracks data-flow facts along feasible program paths
  and a **validator module verifies each fact (data-flow existence + path-condition
  satisfiability) before a bug report is emitted**; that discipline is what gets it to
  ~78% precision at repo level. Transferable lesson: turn "model claims file:line" into
  "model claims file:line AND a mechanical check confirms the line contains the expected
  sink signature" — the check lives in the harness, not in the LLM.
- **Self-consistency as a production technique** (Prompting Guide, updated 2026-02;
  arXiv 2402.13212 as the method reference): sample multiple reasoning paths, score, pick
  the most consistent answer. Full multi-sample is too expensive here (local 27/35B),
  but the cheap form — one **scoring/self-check pass** with the grading rubric in front —
  matches what our report already does mechanically (deliverable_check).
- **OpenAI "Self-Evolving Agents" cookbook (2025-11-04)**: LLM-as-judge with
  **predefined criteria** is the standard evaluation loop; the rubric must be explicit
  (our vulngym/SOC graders are exactly this — the gap is that the agent never sees the
  rubric).

### Proposed fixes

1. **Entry-point vs critical-operation nudge (keep, sharpen).** Add the operational
   definition to the audit prompt: *"critical operation = the line where the untrusted
   value is CONSUMED (exec/formatted/used as a key), not the line where it was produced
   or passed along."* Both vulngym misses were source-side/sink-side confusions
   (airflow: Jinja pusher vs bash_command sink; langchain: call of the resolved
   callable vs the `getattr` key resolution).
2. **Commit-to-one rule.** The langchain failure was a *decision* failure ("the agent
   never commits to it"). Prompt rule: *"Report exactly ONE critical-operation line. If
   you have two candidates, choose the line where untrusted data is consumed, and cite
   in one sentence what value arrives there."*
3. **Harness-side coordinate validator (RepoAudit pattern, cheap).** Extend
   `deliverable_check` for vulngym-family tasks: grep the reported `file:line` (and the
   reported span) and require ≥1 keyword from a per-task-type sink set (template
   injection: `getattr|__getitem__|format|render`; shell injection: `xcom_pull|bash|
   subprocess`). On miss → auto-`next_round` with the hint *"your reported line does not
   contain the expected sink — check whether you traced the source side instead."*
   Zero LLM tokens, converts a zero-tolerance grader miss into a pre-verdict signal.
   This is the single highest-leverage C1 fix.
4. **MITRE selection (s3-insider T1530/T1078 vs T1537).** Two parts:
   - **Prompt rule:** *"Choose the technique for the ACTION evidenced in the logs
     (which bucket operation the attacker performed), not for the account/credential
     they used."* T1078.003 (Valid Accounts: Cloud Accounts) is the account; the S3
     bucket discovery/access is the action — that is the recurring miss in both
     bf0ef6 (T1078.003) and the manual-run retry log (T1548.005 → T1078.004…).
   - **KB arm:** run the one-shot `+mitre-kb` A/B the report suggests. Caveat from
     project memory: the 2026-09-04 arm sweep (pre-v6-rewrite agent) found `+mitre-kb`
     **worst** (socbench 2/18) — that result is stale relative to the v6 rewrite and
     the pinned v19.2 KB + semantic expansion (P@5 20%→40%), so re-measure before
     concluding. Also worth one KB-content check: do the T1530/T1537/T1078 rows carry
     "use vs don't use" disambiguation, or only name/alias?

## C2 — Defensive-coding gap (cwe918-java cast, 0/13)

**Research finding: there is nothing current to borrow.** Web search for LLM +
Java downcast only returns the 10-year-old standard pattern (instanceof-before-cast).
The fix is prompt + verification discipline, and the repo already contains the ground
truth (`solution/solve.sh` uses the guard; the FunctionalTest the agent never ran would
have caught the ClassCastException).

### Proposed fixes

1. **One hard constraint in the code-fix prompt:** *"Guard every downcast with
   `instanceof`; the code must not throw on objects that are not the cast type, even if
   the API usually returns the subtype."* (Report's recommendation; confirmed
   highest-ROI single line.)
2. **Run-the-project-tests rule (from the bf0ef6 deep dive, which the 24h report
   folded in but should make explicit):** cwe918's agent verified with `javac` + grep
   and never ran the offline `mvn` suite that the verifier runs. Add to the work
   prompt: *"If the project ships a test suite, run it (offline) and make it pass
   before reporting done. The grader runs the project's own tests."* This generalizes
   beyond cwe918 to every seccodebench task.

## C3 — Time-budget exhaustion, read-only commit, thinking stalls (whyos, bigboy, tablez)

### What current research says

- **"Towards Budget-Aware Agents: Do LLM Agents Know What They Need?" (OpenReview,
  2026-05):** formalizes budget awareness — agents cannot reliably estimate their
  remaining resource needs mid-execution. Practical corollary: budgets must be
  **injected per request** (remaining time, not just the cap) and the harness must
  enforce termination — you cannot assume the model self-limits. Our `limits_note`
  already renders the cap; extend it to render **elapsed/remaining**.
- **"Steering LLM Thinking with Budget Guidance" (arXiv 2506.13752, 2025-06)** and
  **"Reasoning at the Right Length: Adaptive Budget Forcing" (OpenReview, 2026):**
  test-time control of thinking length without fine-tuning is established practice in
  2025–2026.
- **llama.cpp `--reasoning-budget N`** (verified present in our local build
  `build-cuda/bin/llama-server`: "token budget for thinking: -1 unrestricted, 0
  immediate end, N>0 budget", env `LLAMA_ARG_THINK_BUDGET`; per-request dynamic
  adjustment is the open topic in ggml-org/llama.cpp discussion #21445, 2026-04).
  The 27B's 55–60 s thinking stalls are thinking tokens with no ceiling — a
  server-side budget is the direct fix and needs no agent code.
- **ml4devs, "Why Reasoning Models Blow Your Output Budget" (2026-08-24):** measured
  confirmation that thinking tokens consume the output allowance before any answer
  starts — a long think can eat an entire window with zero visible output (exactly the
  tablez death: 55.5 s call + 30 s final_ask + 60 s review, all zero output).

### Proposed fixes

1. **llama.cpp thinking budget for the stalling endpoint.** Ask the user to restart the
   27B-UD-IQ4_XS server (via `~/starters/`) with `--reasoning-budget N` (e.g. start at
   ~2–4k tokens ≈ 10–20 s of thinking at observed speed; tune). Per-project rules I
   must not touch the server myself — this is a user action. This alone removes the
   "one slow call eats the whole phase" failure mode.
2. **Per-call stall → fresh-context retry (generalize the report's terminal-review
   salvage).** In `TrackedModel`, when a call dies with zero output (wall cap hit or
   stream stall), issue exactly ONE retry in a minimal fresh context ("You were
   verifying X. The deliverable is at PATH. Answer done/next_round + one line.") before
   the phase cap is consumed. The terminal review currently has no fallback — a
   recoverable run died on one slow call (tablez).
3. **Commit must be able to finish (bigboy).** Two-part fix:
   - Prompt rule in commit.md: *"If the deliverable is MISSING or EMPTY on disk, the
     verdict is ALWAYS `next_round`."* (The packet already reports MISSING/EMPTY; the
     rule just has to be explicit.)
   - **Allow commit/repair to CREATE a missing `answer`-kind deliverable when the
     content is already in the commit context** (bigboy: objdump found the flag in
     commit; the read-only commit could not write it). Currently `RepairPhase` enforces
     artifact-only single mutation on an existing file. Minimal change: for
     `kind=answer`, let the verifier's write path create the file with the content it
     states.
4. **whyos search breadth (token lever + C3).** Prompt norm: *"First identify WHO
   wrote the secret (which process logged it); mine that process's log before any
   broad enumeration. Cap candidate enumeration — verify a small shortlist."* Backed by
   the context-engineering literature below (attention budget: breadth-first token dumps
   degrade precision). The manual solve was 8 steps; the agent spent both 120 s work
   caps on breadth-first enumeration of 426 candidates.

## C4 — Trailing spans lost in OTel export

### What current research says

- **OTel spec (Tracing SDK, current):** `ForceFlush` must export all not-yet-exported
  spans; `Shutdown` should block until all spans are flushed or the timeout elapses.
  Spans that end but are never flushed **do not reach the backend** — there is no
  implicit flush guarantee on process exit.
- **opentelemetry-go issue #7596 (2025-11-04):** "Tracer doesn't flush implicitly on
  shutdown" — cross-language confirmation that an explicit flush is required.
- **OneUptime BatchSpanProcessor guide (2026-01-30):** the canonical pitfall list —
  "spans in the queue are lost if you do not flush before shutdown"; the pattern is a
  SIGTERM handler calling `provider.shutdown()` (which force-flushes).
- **Mechanism here (verified in code):** `telemetry/__init__.py` uses
  `BatchSpanProcessor(exporter)` with defaults (`schedule_delay_millis=5000`): finished
  spans sit in the queue up to 5 s. The runner's docker-exec hard timeout kills the
  process; a SIGKILL'd process runs no atexit/SIGTERM handlers and never calls
  `force_flush`. `_ShlepaSpanProcessor` even documents the symptom ("a trace whose
  agent.run root span never flushes (docker kill on a hard exec timeout)").

### Proposed fixes (concrete)

1. **Flush after every LLM call.** The usage-recording path (`_ShlepaSpanProcessor`
   `on_end` / usage event) is the natural hook: call
   `provider.force_flush(timeout_millis=1500)` there. Spans are small, the collector is
   local — cost is negligible, and the lost window shrinks from "last up-to-5 s +
   in-flight" to "since the last completed LLM call." (Alternative: lower
   `schedule_delay_millis` to ~500 — same effect, more small POSTs.)
2. **Explicit flush on every end path, where termination is already stamped.**
   `mark_termination(reason)` (telemetry `__init__.py:410`) and the `root_span`
   exception path both already run on the way out — add `force_flush(5000)` there, plus
   a SIGTERM handler + `atexit` backstop in the telemetry init. This covers graceful
   kills and the normal path; SIGKILL remains unflushable, which is why (1) matters.
3. **Runner-side termination tag on EVERY end path (report gap #2), independent of
   traces.** The CLI already classifies the kill (run_engine.py:895–903:
   `exec_timeout` from exit 137, `oom`, `timeout`). Tag the **MLflow run** (not only
   the trace span) with `termination_reason` on all paths, so a trace whose tail was
   SIGKILL'd is still diagnosable: run has wall time + termination tag + token metrics,
   trace has the surviving prefix.
4. **Loop signal false positives (report gap #3).** Hash `command + args` and require
   repetition of the *identical* command (e.g. ≥3 same-hash within the window) instead
   of counting invocations. Also fix the related dead code: `trace_digest.py` reads
   `tool.call.arguments`, which does not exist in real traces (issue #68) — real tool
   spans carry `gen_ai.tool.call.arguments` / `tool.parameters` / `input.value` and
   `gen_ai.tool.call.result` / `output.value`, so loop detection and result-dedup are
   currently inert.

## Token levers — what current practice says

- **Anthropic, "Effective context engineering for AI agents" (2025-09-29):** the three
  levers are **compaction, structured note-taking, sub-agent isolation**; core concept
  is the **attention budget / context rot** — precision degrades as context grows, so
  context is a finite resource. Direct support for: (a) trimming plan (21.7% of tokens
  for tasks with 5-step manual solutions) — "recon + outline" is the lean plan;
  (b) whyos breadth-first search — breadth dumps spend the attention budget;
  (c) multi-cycle re-planning — each cycle re-bills a fresh conversation; cutting cycle
  count (via the C1/C3 fixes) is the same lever.
- **Prompt caching (current vendor docs):** Anthropic (platform.claude.com, current):
  cache = **byte-identical prefix**, automatic or explicit breakpoints, 5-minute
  (or 1-hour) TTL. OpenAI (developers.openai.com, current): automatic, minimum
  cacheable prefix (1024 tokens on GPT-family), prefix must match exactly. LMCache,
  "Context Engineering & Reuse Pattern Under the Hood of Claude Code" (2025-12-23):
  agent frameworks get their cache rates from **stable conversation prefixes that are
  never rewritten mid-conversation**.
  **Applied to the commit-phase loss (54.6% vs 88.1%):** the v6 commit runs a
  **fresh** conversation (verify packet) — 0% first call is by construction, not a bug.
  The A/B knob already exists (`SHLEPA_REVIEW_CTX=full` resumes the trimmed work
  conversation). If the work context is ~23K (sampled) and 99% cached, resuming costs
  ~2–3K effectively-new vs 23.3K fresh — **resuming wins on tokens**; fresh wins on
  context hygiene (lean verifier). Run the fresh-vs-full A/B arm on the 17-task set and
  let `tokens_cache_read.commit` decide; if fresh stays, the saving is bounded and
  should be deprioritized vs the plan-trim.
  If the endpoint is local llama.cpp, also check the server's KV/slot config in
  `~/starters/` (prefix reuse requires the same slot and no eviction between the last
  work call and the commit call — the mixed 54.6% average suggests some evictions).
- **Per-task ceilings on 0-solve tasks (report lever):** current practice for bounded
  agent work is external budget enforcement (the "budget-aware agents" line above) —
  our runner is the right place (a per-task token/time ceiling knob in the preset),
  not the prompt.

## Cross-cutting notes

- **C5 (model noise on medium tasks)** — no research needed; it is the residue of C4
  (undiagnosable early aborts). Fixing C4's termination tagging will let us reclassify
  bigboy/cwe79-go failures as "early abort" vs "one-shot miss" before spending on
  anything.
- **27B vs 35B comparison (open item):** keep as a controlled arm run; the
  `--reasoning-budget` finding changes the comparison — the 27B's apparent "thinking
  quality" issues are partly uncapped thinking.
- **Recency policy:** all primary sources above are 2025–2026 (vendor docs, ICML 2025,
  arXiv 2025-06, OpenReview 2026, llama.cpp 2026). The only 2024 item (soft
  self-consistency arXiv) is cited as method reference only, per the user's
  no-outdated-data constraint.

## Disposition (2026-09-10, user decision)

- **Dropped (user):** all MITRE work (C1 fix 4 — no `+mitre-kb` arm, no prompt rule), all of C3 (no `--reasoning-budget` server change, no stall-retry/commit-write/whyos prompt fixes), and all token levers.
- **Filed:**
  - #126 — OTel flush after each LLM call + on every exit path (C4)
  - #127 — trace root span `termination_reason` on all exit paths (C4)
  - #128 — mechanical sink-keyword check on reported `file:line` (C1, fix 3)
  - #129 — work-prompt instanceof guard (C2, fix 1)
- **Extended:** #124 (audit prompt nudge) — added the "consumed, not produced" definition + commit-to-one rule (C1 fixes 1–2).
- **Already covered, not filed:** C2 fix 2 (run project tests) = existing #122; loop-signal false positives + `trace_digest` dead code = #68 (closed, fix verified in `tool_signature`); MLflow-run termination tagging = #35 (closed).

## Source list

| # | source | date | used for |
|---|--------|------|----------|
| 1 | RepoAudit — ICML 2025 poster (icml.cc/virtual/2025/poster/45170; github.com/PurCL/RepoAudit) | 2025-07 | C1: verified-facts auditing, validator module |
| 2 | Prompting Guide — Self-Consistency (promptingguide.ai/techniques/consistency) | 2026-02 | C1: consistency as standard technique |
| 3 | OpenAI Cookbook — Self-Evolving Agents (developers.openai.com) | 2025-11-04 | C1: rubric-as-judge practice |
| 4 | "Towards Budget-Aware Agents" — OpenReview rdqxBAeW1C | 2026-05 | C3: budgets must be injected/enforced |
| 5 | arXiv 2506.13752 — Steering LLM Thinking with Budget Guidance | 2025-06 | C3: thinking-length control |
| 6 | "Reasoning at the Right Length: ABF" — openreview ieBgxTG7Mt | 2026 | C3: adaptive thinking budgets |
| 7 | ggml-org/llama.cpp — `--reasoning-budget` flag (verified locally) + discussion #21445 | 2026-03/04 | C3: server-side thinking cap for 27B stalls |
| 8 | ml4devs — Why Reasoning Models Blow Your Output Budget | 2026-08-24 | C3: thinking eats output budget with zero output |
| 9 | OpenTelemetry spec — Tracing SDK (ForceFlush/Shutdown) | current | C4: no implicit flush on exit |
| 10 | opentelemetry-go issue #7596 | 2025-11-04 | C4: explicit flush required (cross-SDK) |
| 11 | OneUptime — BatchSpanProcessor guide | 2026-01-30 | C4: queue-loss pitfall + shutdown pattern |
| 12 | Anthropic — Effective context engineering for AI agents | 2025-09-29 | plan trim, whyos breadth, multi-cycle, context rot |
| 13 | Anthropic prompt-caching docs (platform.claude.com) | current | commit cache: byte-identical prefix, TTL |
| 14 | OpenAI prompt-caching guide (developers.openai.com) | current | commit cache: automatic, min prefix |
| 15 | LMCache — Context Engineering & Reuse in Claude Code | 2025-12-23 | commit cache: stable-prefix agent pattern |
