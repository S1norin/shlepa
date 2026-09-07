# Work plan: Agent v6.1 — stagnation guard & finalization reserve

**Status:** draft for review. **Date:** 2026-09-02. **Branch (when started):** `feature/agent-stagnation-guard`.
**Companion plan:** `docs/plans/agent-v6-pipeline-hardening.md` (v6 pipeline: plan gating,
routing, handoff). This plan is the **second workstream**: detecting and preventing *wasted
budget* (retries/redundant commands burning phase caps) in WORK/PLAN. It builds on the v6
A/B harness (arm tags, env knobs, mini preset) and needs v6 Phase 0 (digest/telemetry fixes)
as a measurement prerequisite.
**Sources:** trace review 2026-08-31→09-01 (448 traces), three external research reports on
loop/stagnation detection in capped local-model agents (references in §8), current codebase
(verified).

---

## 1. Evidence base

### 1.1 What our data says

- The corrected loop detector (exact argument hash, `≥4 identical within 6`) found **0 true
  loops in 448 runs**. One-sided 95% upper bound on per-run prevalence ≈ 0.67%
  (`1 − 0.05^(1/448)`). Exact-argument looping is not our failure mode.
- The broken detector (wrong attribute key → "any 4 bash calls in a row") produced **256 false
  positives in one 319-run window** (≈0.80 bogus events/run). Lesson: proxy signals must be
  unit-tested against raw spans before they influence anything.
- The only real failure observed is **wasted budget**: models re-run failing or redundant
  commands and burn phase caps (near-identical variants: same grep with different flags, same
  failing test 3×, same file region re-read) — not tight programmatic loops.
- The WORK prompt **already** says: "If a step fails twice, adapt within the plan's scope with
  the smallest change; never switch strategy wholesale. Never run the same failing command more
  than twice." The rule is violated in traces ⇒ this invariant is too important to live in
  prose for 27–35 B models (the 27B/35B phase-discipline gap, 71% vs 31%, is our standing
  internal evidence that prompt compliance is fragile).
- Phase caps abort in-flight requests: "almost finished" and "made no progress" currently end
  identically — no valid structured phase result.
- **Level-A replay confirmation (2026-09-02, 474 traces / 14 batches, 35B+27B — see
  [`docs/analysis/2026-09-02-stagnation-replay.md`](../analysis/2026-09-02-stagnation-replay.md)):**
  strict candidates **0**; immediate identical re-runs **1/474**; consecutive fuzzy retries
  (ratio ≥ 0.8) **0**; non-consecutive repeats **19/474 (4.0%)**, all benign retry-after-change
  (re-read after edit, pytest re-run). The models reformulate every attempt, so exact-match
  enforcement has zero targets on this corpus — **Phase B is downgraded to shadow-only**
  (ledger + log, no hard stop) pending production shadow data; the observed waste is REVIEW
  drift, addressed by the review redesign workstream.

### 1.2 What the research reports say (three reports, converging)

All three independently reject "loop detection" as the frame and land on the same ranking:

> **waste = equivalent attempt ∧ equivalent adverse/no-op outcome ∧ no relevant state change.**

1. **Replace the exact-loop detector with an outcome- and state-aware stagnation guard
   enforced at the tool boundary**: allow attempt 1, warn after equivalent failure 2, **block
   the 3rd equivalent no-progress attempt** (directly operationalizes our existing "twice" rule);
   on block, escalate to REVIEW/next PLAN — never kill the task.
2. **Phase-budget visibility + measured finalization reserve**: inject per-turn
   `phase/elapsed/remaining`; when `remaining ≤ R` (R = P95 of successful final-result latency
   + margin, per model+phase), enter finalization-only mode (no new exploratory tools; minimal
   write/edit allowed to land the deliverable). Evidence: Budget-Aware Tool Use (36.8→55.4,
   frontier — medium transfer), BAGEN (budget awareness r≈0.35; 28–64% token savings on failed
   runs, 1.6–4.2% success cost), real-time-deadline study (32% vs 4% closure with per-turn
   remaining-time vs one-shot deadline).
3. **Failure ledger / duplicate-context compression**: keep the first raw failure diagnostic;
   when an equivalent attempt recurs, replace the older duplicate's model-visible content with a
   compact `attempt_family=…; attempts=2; outcome=same; state_unchanged` line. Mechanistic
   anchor ("Feedback That Backforces", ≤1.7B models — do **not** transfer their 76% number):
   small models repeat the call whose surface form they just saw fail; abstracting it removed
   most of the inversion.
4. **Retain exact-repeat hashes as telemetry only** (cheap predictive feature; the 413K-trace
   observational study found exact bash repetition twice had 59.6% within-issue failure
   concordance vs 53.5% for "4+ consecutive bash").
5. Counter-evidence that shapes the design: **71% of successful CLI-agent trajectories recover
   from ≥1 error** (block #3, not #1/#2); **AgentQuest** — repetition can coexist with progress
   (state-change resets, fail-open on uncertain state); **SWE-agent ACI** — structural tool
   guardrails are a first-order performance variable (+10.7 pt ablation, frontier); **Agentless**
   — constraining autonomy where structure is known.

### 1.3 Current state (verified in code)

| fact | where |
|---|---|
| `bash` tool **already** returns a structured envelope: `$ cmd / [cwd] / [exit_code] N` (124 + `KILLED after Ns timeout` marker on timeout), `[stdout]`, `[stderr]`, head+tail bounded retention (≤ `max_output`), per-call 30 s cap; raw result logged via `_log_event("tool_result", exit_code=…, stdout=…, stderr=…)` | `agent/shlepa_agent/tools/bash.py` |
| Tools are `Tool(name, note, run)` records in `ALL_TOOLS`, resolved per phase by `get_tools(cfg, names)`; every tool runs as `run(RunContext[AgentDeps], …)`; `AgentDeps(workdir, cfg, clock)` is shared per model/run and **already carries a clock** (`TrackedModel.elapsed`) | `agent/shlepa_agent/tools/__init__.py`, `tools/base.py`, `runner.py` |
| Phase caps are rendered **once** into the phase prompt (`limits_note`: "this phase is hard-capped at 60s"); `soft_time`/`soft_tokens` exist as advisory knobs; **no per-turn remaining-time header exists** | `agent/shlepa_agent/phases/base.py`, `config.toml` |
| `TrackedModel` (our `OpenAIChatModel` subclass) already owns `request_stream(messages, …)` per request, `last_messages`, usage logging, and the 180 s per-request wall — **the natural hook for per-turn status injection and context compression** | `agent/shlepa_agent/model.py` |
| The WORK retry rule is prompt-only (see §1.1); there is **no harness-side retry state** | `agent/shlepa_agent/prompts/work.md` |
| Tool spans in MLflow traces carry `tool.parameters`, `output.value`, duration, tokens → offline replay of any detector is possible on the existing 448 runs | `tmp/trace-export/*/traces/*.json`, trace experiment |
| Digest `loop:*` signal is broken (wrong keys) → v6 pipeline plan Phase 0.1 fixes it; **prerequisite** for trustworthy shadow replay | `cli/shlepa_cli/trace_digest.py` |
| `phases/emergency.py` is **dead v4 code** (explicitly unwired in v5) — not a finalization mechanism; do not build on it | `agent/shlepa_agent/phases/emergency.py` |
| Per-request durations are logged (`usage`/`agent_done` events carry `elapsed_s`; `final_ask` events exist) → P95 finalization latency per model+phase is computable from existing telemetry | `agent/shlepa_agent/model.py`, `runner.py` |

---

## 2. Target design (v6.1)

### 2.1 Stagnation guard (the core)

Rename the concept everywhere from `loop` to **`stagnant_repeat`** (a loop is one rare species of
stagnation we do not observe). The guard is a **deterministic per-phase ledger** in the harness,
not a model.

**Where it lives (single implementation):** `agent/shlepa_agent/retry_guard.py` — pure, no
telemetry dependency (zip-safe): canonicalizers, outcome fingerprints, `AttemptLedger`. The CLI
replay (`cli/shlepa_cli/stagnation.py`) imports it, so offline calibration and live enforcement
never drift apart.

**Attempt identity (two levels):**

| level | scope | examples | action |
|---|---|---|---|
| **A — safe canonical (enforceable)** | per-tool deterministic rules | `read`: normalized path + ≥80% page/offset overlap + file version unchanged. Recognized test commands (`pytest/unittest/tox/nox`): same selected targets, presentation flags (verbosity/color) ignored, semantic flags kept. Recognized search (`grep/rg/find`): same pattern + roots, formatting flags ignored. Generic `bash`: whitespace/quote-normalized **exact** match only. `write/edit`: never fuzzy; duplicate only for same target + same payload with file version unchanged | eligible for warn/block |
| **B — near-equivalence (telemetry only)** | normalized token Jaccard ≥ 0.9 / edit-distance bands | `pytest x -q` vs `pytest x -vv`, `grep -i a` vs `grep a` | logged as `stagnant_near`, **never** hard-blocked |

**Outcome fingerprint:** exit class (`0` / non-zero / `124` timeout) + stable normalized output
hash (strip ANSI, timestamps, PIDs, temp-path suffixes, test timing); for test failures:
failed-test IDs + exception class + top stable frame. Two outcomes "equivalent" = same exit
class + line-level Jaccard ≥ 0.90 on normalized output.

**State change (reset conditions):** a `write`/`edit` to a relevant path bumps that path's
version in the ledger and resets attempt families whose prerequisites include it
(`pytest T → edit T's source → pytest T` is legitimate). **Fail-open rule:** any `bash` call can
mutate the workspace; if the ledger cannot establish relevant state is unchanged, a candidate
block downgrades to `warn` (execute + log). No hard block on uncertain state.

**Thresholds & actions (enforce mode):**

| attempt # (same canonical family, same outcome, no reset) | action |
|---|---|
| 1 | normal execution |
| 2 | execute; append to the tool result: `RETRY_STATE same_attempt=2/2 outcome=unchanged; another equivalent call will be blocked — change the diagnostic, edit a file, or finalize.` |
| 3 | **do not execute**; return synthetic result `RETRY_GUARD_BLOCKED: this attempt is equivalent to two prior attempts with the same outcome and nothing relevant changed. Do not retry locally: call final_result now (done=false, reason="stalled_retry") reporting the failed hypothesis and evidence.` |
| 2 blocks in one phase | same synthetic result plus: "this phase is over — finalize now." Backstop: the phase cap still aborts if the model disobeys (worst case = current behavior, never worse). |

In WORK, a `stalled_retry` finalization routes to REVIEW exactly like a normal `done=false`
(re-diagnose there; the next PLAN may change strategy — strategy stays out of WORK, per the v6
design invariant).

**Shadow mode (default, first deployment):** identical detection, **no blocking**, no injected
notes; every candidate logged with full context (`detector_version`, raw args, canonical key,
rule used, prior span IDs, outcome fingerprint, similarity, phase/remaining time, model, task).
Shadow runs alongside v6 for ≥1 mini batch + the 448-run offline replay before any enforcement.

### 2.2 Failure ledger (context compression, model-visible)

In `TrackedModel.request_stream` (our wrapper, pre-request): scan `last_messages` for the
ledger's duplicate families; for the 2nd+ occurrence of an equivalent failed attempt, replace
the tool result body in the outgoing messages with one compact line:
`[attempt_family=test:tests/test_x.py attempts=2 outcome=identical-failure source-unchanged]`
(raw content stays in telemetry/spans; the **first** occurrence is never compressed — its
traceback is the diagnostic). No new tools, no extra context — net context is *smaller*.

### 2.3 Phase-budget header + finalization reserve

- **Header:** every model request gets a compact machine-generated line prepended
  (in `TrackedModel.request_stream`, from `AgentDeps.clock` + the phase cap known at model
  construction): `[phase=work elapsed=73.1s remaining=46.9s]`. Only the phase clock the harness
  knows — never an invented task-wide deadline.
- **Reserve:** per model+phase `R = min(0.30·cap, max(5s, P95(finalization-latency) + 2s))`,
  computed from our own telemetry (existing request-duration events) by a CLI utility; until
  measured, static defaults (plan 10 s / work 20 s / review 10 s) as config values.
  When `remaining ≤ R`: **finalization-only mode** — the guard rejects *new exploratory* calls
  (`read`, `bash`, `edit` with synthetic `FINALIZING: no new exploration — write the deliverable
  and call final_result`), while `write`/`edit` to the deliverable path stay allowed. This
  structurally eliminates "useful work eats the seconds needed to emit final_result" (our
  observed aborted-final-request cohort: 17% solved vs 61% clean).
  Distinct from the existing post-cap `_final_ask`: the reserve acts **before** the cap, while
  the model still has tools.

### 2.4 Envelope status

Report-level "structured bash interface" recommendations are **largely already implemented**
(`[exit_code]`/124/timeout marker, bounded output, raw logging). No new envelope work; the
guard consumes `_log_event` data + tool results directly.

---

## 3. Work items

Depends on: v6 pipeline plan Phase 0 (digest keys — trustworthy spans) and Phase 1 (arm tag,
mini preset, env-knob mechanism). The guard branch itself does not depend on v6 pipeline
changes landing (env knobs are independent), but A/B arms run on the v6 build.

### Phase A — offline replay & calibration (shadow)

| # | item | files | AC |
|---|---|---|---|
| A.1 | `retry_guard.py`: canonicalizers (Level A per-tool rules + Level B near-metrics), outcome fingerprints (normalization: ANSI/timestamp/PID/temp-path strip; test-failure extraction), `AttemptLedger` (families, versions, resets, fail-open), `detect(events) -> candidates` pure function + **unit tests with real telemetry field names as fixtures** (regression test for the wrong-key incident: 4 different bash cmds → no fire; identical normalized args → fire; JSON key order / whitespace changes → same hash) | `agent/shlepa_agent/retry_guard.py`, `agent/tests/test_retry_guard.py` | Unit tests green; canonicalizer importable with no telemetry/otel imports (zip-safe assertion test) |
| A.2 | Offline replay over the 448 exported traces: per run — candidates, would-be-warn/block, `T_candidate = Σ duration(blocked)` by phase, false-positive audit sample (stratified, hand-labelled) | `cli/shlepa_cli/stagnation.py` (new; `shlepa stagnation <batch>`), reuses A.1 | Report: candidates/run, candidate-seconds/run, % of WORK time, by model (27B/35B) and task class; **gate:** Level-A families ≥95% precision on the labelled sample; if `T_candidate` < ~5% of phase wall time overall ⇒ skip Phase B enforcement, keep telemetry only |
| A.3 | Finalization-latency stats: P95 per model+phase of the request that produced a valid `final_result` (from existing events) → recommended `R` values | `cli/shlepa_cli/finalize_stats.py` (or flag on `stagnation`) | Table of recommended reserves; committed as config defaults when adopted |

### Phase B — live guard (shadow → enforce)

| # | item | files | AC |
|---|---|---|---|
| B.1 | Per-phase `AttemptLedger` instance in `AgentDeps` (created at phase start in the runner); tool-call path consults the ledger via a wrapper around `Tool.run` (all tools, single wrapper — the ledger sees every call); shadow mode logs candidates as agent events (`stagnant_candidate`, with all §2.1 fields) | `agent/shlepa_agent/tools/base.py` (wrapper), `runner.py` (ledger lifecycle), `config.toml` | Shadow run: candidates appear in agent log + spans; **zero** behavioral change (diff of tool results vs no-guard run = empty) |
| B.2 | Enforce mode: warn on #2, synthetic block on #3, double-block finalization push (§2.1 table); env knob `SHLEPA_GUARD_MODE=off|shadow|warn|enforce` (default `shadow`) + `docs/agent-config.md` row | same files, `agent/tests/test_retry_guard.py` + `tests/test_runner.py` | Routing unit tests: 3rd equivalent call returns synthetic result and is not executed (mock tool asserts no side effect); `SHLEPA_GUARD_MODE=off` ⇒ wrapper identity |
| B.3 | `stalled_retry` handling in WORK: accepted by `WorkResult`/runner as a normal `done=false` → REVIEW (verify no special-casing needed; add `reason` passthrough if missing) | `agent/shlepa_agent/outputs.py`, `runner.py` | A stalled WORK lands in REVIEW with the hypothesis text in the conversation |

### Phase C — budget header + finalization reserve

> **Mandatory since 2026-09-02 (official rules, see §1.5 of the review-redesign plan):** each task
> has its own time **and token** limits that are NOT communicated to the agent (`run.sh "<instruction>"`
> is the only input); timeout/crash = 0 even with a correct file on disk; v5 currently has NO global
> clock and NO token budget (config.toml). Phase C is no longer a "nice to have" — it is the fix for
> the killed-round cohort. **Anchoring rule: the limits are invisible, so Phase C uses only known
> quantities (phase caps, own elapsed) and observed signals (endpoint failures) — never a guessed
> deadline or token cap.** Sample public tasks: `agent.timeout_sec` 120 s (trivial) – 600 s (medium).
> These calibrate *expected* run length (be-faster strategy), not a parameter the agent reads.

| # | item | files | AC |
|---|---|---|---|
| C.1 | Per-turn header injection in `TrackedModel.request_stream` (phase id + cap known via constructor; clock via deps): `[phase=work elapsed=… remaining=…]`; knob `SHLEPA_BUDGET_HEADER=0/1` (default 1) | `agent/shlepa_agent/model.py`, `runner.py`, `config.toml` | Unit test: captured outgoing messages carry the header with correct monotonic remaining; provider round-trip smoke OK |
| C.2 | Finalization-only mode at `remaining ≤ R`: ledger rejects new exploratory tool calls with the `FINALIZING` synthetic result; `write`/edit-to-deliverable allowed; `R` from config (defaults from A.3); knobs `SHLEPA_RESERVE_PLAN/WORK/REVIEW` (s) | `retry_guard.py`, `tools/base.py` | Unit test: with fake clock at cap−R+ε, `bash`/`read` blocked, `write` allowed; no cap-abort in the reserve window in a synthetic run |
| C.3 | **Reactive finalization on observed terminal signals (new):** no guessed token cap — instead, when the LLM endpoint starts failing terminally (repeated 429/402, repeated connection errors on the request stream — the only *observable* proxy for hitting an external token cap or endpoint death), the harness stops new requests, ensures the best deliverable is on disk, and exits `run.sh` **normally** (exit 0) with `exit_reason=endpoint_finalized`. Rationale: a killed/crashed run is 0; a normal exit is the only state in which the verifier runs | `model.py`, `runner.py`, `log.py` | Unit test: fake stream emitting 3 consecutive 402s → no further request sent, run ends with exit code 0 and `exit_reason=endpoint_finalized`; single transient 503 with successful retry does NOT trigger it |

### Phase D — failure ledger (context compression)

| # | item | files | AC |
|---|---|---|---|
| D.1 | Duplicate-failure compression in `TrackedModel.request_stream` using the ledger's families: 2nd+ equivalent failed tool results replaced by the compact line (§2.2); first occurrence never compressed; knob `SHLEPA_LEDGER_COMPRESS=0/1` (default 1) | `agent/shlepa_agent/model.py`, `retry_guard.py` | Unit test: a conversation with 3 identical failed test runs sends the compact line for runs 2–3, full output for run 1; context token count drops (measured in test) |

### Phase E — experiments

| # | item | notes |
|---|---|---|
| E.1 | Mini A/B (11-task mini preset, 35B, n=1) on the v6 build: **G0** = v6, guard off · **G1** = +budget header +reserve (C) · **G2** = G1 + guard enforce, Level-A only (B) · **G3** = G2 + ledger compression (D) | 44 runs ≈ 4 h; sequential batches only |
| E.2 | Full 35B sweep of the winner (n=1) + n=3 stability on mini | gate: no control-task regression |
| E.3 | 27B mini check (G-winner vs G0) — the 71%-discipline cohort is where header/reserve should bite hardest | optional, after 35B verdict |

**Success criteria (35B full sweep, vs G0):**
- **Primary:** solved rate flat-or-up **and** wasted-seconds metric down:
  `Σ duration(blocked-equivalent calls)` per run ↓ ≥ 50%, and phase cap-abort rate ↓.
- **Mechanism (per model+phase):** `valid_final_result_rate` ↑; share of runs ending in the
  reserve (not in an aborted in-flight request) ↑.
- **Safety:** false-block rate on successful trajectories < 1% (shadow-labelled set carried
  forward); easy controls stay 100%.

## 4. Failure modes and counter-evidence

- **Legitimate repetition:** retest-after-edit, flaky-test confirmation, polling. Covered by
  state-change resets + outcome inequality + fail-open on uncertain bash. Residual risk: flaky
  tests where "same failure" is still informative — the 2-strike allowance absorbs one; block #3
  is a policy tradeoff, documented.
- **Near-similarity ambiguity** (`pytest x` vs `pytest x -k regression`): Level B is telemetry
  only; never blocks.
- **27B re-reading because it lost track:** blocking re-reads could hurt; we block only
  same-family ≥80% overlap *within a 6-call window with unchanged file version* — short horizon,
  and the `FINALIZING`/stall paths prefer ending over grinding.
- **Premature finalization cost:** BAGEN reports a ~1.6–4.2% success cost for early stopping.
  Mitigation: reserve is finalization-only (still allows the deliverable write), and the cap
  remains the backstop; E.1 isolates this (G1) before it compounds.
- **What changes the verdict:** (a) A.2 shows candidates < ~5% of phase wall time → drop
  enforcement, keep telemetry; (b) A/B shows solved ↓ while tool-time ↓ → revert fuzzy
  enforcement to log-only; (c) shadow labelling finds > 1–2% of would-be blocks on *successful*
  traces are load-bearing → tighten (or disable) the offending family; (d) overrun rates stay
  flat after C ⇒ the dominant overrun cause is model latency/invalid JSON, not scheduling → fix
  finalization reliability (schema-repair retry) instead.
- **Strongest opposing view (kept on record):** AgentQuest/Reflexion show iteration and
  feedback-driven repetition can be productive; the guard therefore suppresses *non-progress*,
  not iteration — and every block is reversible (REVIEW re-diagnoses).

## 5. What we will NOT do

- Not restore "4 bash calls in a row" or promote `exact ≥4` as an intervention (0/448; dead
  primitive for our workload).
- No LLM-based redundancy/stuck judge (constraint: no extra models; RedundancyBench's best
  step-level LLM judge scores only ~25%).
- No fuzzy hard-blocking of generic bash (whitespace-normalized exact only; Level B = log).
- No exponential backoff between retries (wall time is the scarce resource; broken tests don't
  heal while sleeping) — borrow the retry-*budget/circuit-breaker*, not the waiting.
- No global tool-call caps or blanket cap reductions (allocation within the cap is the problem).
- No "force a wholesale strategy switch" on block (force *difference*, re-diagnosis belongs to
  REVIEW/next PLAN).
- No stripping the first raw error/traceback from context (it is the diagnostic; compress only
  duplicates).
- No invented task-wide deadline in prompts (we don't know it); only the phase clock.
- No building on `phases/emergency.py` (dead v4 code; delete in a separate cleanup PR if
  desired).
- No transfer of external effect sizes (SWE-agent +10.7 pt, PMCoder +5 pt, "76% inversion
  removal") into our expected gains — mechanism anchors only.

## 6. Sequencing & effort

| phase | effort | depends on |
|---|---|---|
| A (replay/calibration) | 1–1.5 d | v6 plan Phase 0.1 (digest keys) |
| B (live guard) | 1 d | A.1, v6 plan Phase 1 (knobs) |
| C (header/reserve) | 0.5–1 d | A.3 |
| D (ledger compression) | 0.5 d | B (ledger), C (same hook) |
| E (experiments) | 1 d machine + analysis | v6 pipeline landed, B–D |

Before PR: `shlepa smoke` + `shlepa zip` (guard is pure-python, zip-safe; assert in tests),
agent test suite green. Conventional commits, one logical change each
(`feat(agent): retry guard shadow`, `feat(agent): finalization reserve`, `feat(cli): stagnation
replay`, …).

## 7. Open questions (decide before Phase B)

1. Ledger scope: per-phase (proposal — phase boundary resets families) vs per-run with decay?
   Per-phase matches our cycle structure and the 6-call window.
2. `pytest`/`grep` canonicalizers: hardcode the two families (proposal) or a small
   command-family registry in config? Start hardcoded; registry if E.1 shows other families
   dominate.
3. Reserve defaults until A.3 stats exist: plan 10 / work 20 / review 10 (proposal) — check
   they don't truncate legitimate late edits on the 11-task mini set in dry analysis.
4. Should the header also carry `retry_state=n/2` for the active family (cost: one line;
   benefit: the model sees its own strike count)? Leaning yes — it turns the guard into
   visible policy instead of a surprise.
5. 6-call window vs full-phase window for Level A: proposal keeps 6 (locality evidence,
   RedundancyBench window ablations) — revisit if replay shows families spanning >6 calls.

## 8. References

Internal:
- Trace review 2026-08-31→09-01 (448 traces; 0 true loops / 256 false positives; wasted-budget
  failure class; 71%/31% phase discipline).
- Companion: `docs/plans/agent-v6-pipeline-hardening.md`.
- Code: `agent/shlepa_agent/{model.py,runner.py,budget.py}`, `tools/{base.py,bash.py,read.py,
  write.py,edit.py,__init__.py}`, `phases/{base.py,emergency.py}`, `prompts/work.md`,
  `cli/shlepa_cli/trace_digest.py`, `tmp/trace-export/*/`.

Research reports (three independent LLM analyses, same prompt; key external sources):
- **Failure as a Process** (1,794 CLI trajectories, 2026): 82% of failed runs keep executing
  after failure is unrecoverable; wrong-problem repair 39% of wasted execution; same-approach
  repetition 29%; 71% of successful runs recover from ≥1 error.
- **RedundancyBench** (2026): redundancy taxonomy (duplicated/abnormal/incorrect/exploratory);
  window-3 context beats single-step and full-trajectory inspection; best LLM step-level judge
  24.88%.
- **BAGEN** (2026): budget awareness r≈0.35 vs task ability; 28–64% token savings from
  early-stop on failed runs, 1.6–4.2% success cost.
- **Budget-Aware Tool Use** (2025/COLM 2026): 36.8→55.4 SWE-bench Verified with continuous
  remaining-budget exposure (frontier models; medium transfer).
- **Real-time deadlines** (2026): 32% vs 4% closure with per-turn remaining time vs one-shot
  deadline.
- **Feedback That Backfires** (2026, ≤1.7B models): failure transcript raises repeat
  probability 0.06→0.54; abstracting the failed call removes ~76% of inversion (scale-limited).
- **PMCoder** (2026): execution-grounded stuck detection, +5.0 pt / 25 cases (domain-adjacent).
- **Infinite agentic loops** (2026 static analysis, 6,549 repos / 68 confirmed): real but
  structurally different from our retry waste.
- **We analyzed 413K agent runs** (2026): exact bash repeat twice — 59.6% within-issue failure
  concordance; "4+ consecutive bash" 53.5% (below significance bar).
- **Aghzal et al., ACL 2026** (web agents): low-level execution the dominant bottleneck; ~10.4%
  of failures involve repeated actions; ~34% of actions redundant/no-state-change.
- **AgentQuest** (NAACL 2024): repetition vs progress measured separately; dedup helps some
  settings (47→60, 43→62), can hurt others.
- **SWE-agent** (NeurIPS 2024): ACI ablation +10.7 pt; bounded interfaces, concise feedback,
  empty-output messages.
- **Agentless** (FSE 2025): structured localize→repair→validate, 32.67% SWE-bench Lite.
- **AgentBench** (ICLR 2024): OSS ≤70B gap; instruction-following/long-horizon failures.
- **Lee et al., ACL 2026** (tool-schema adaptation): up to 17-pt gains, 80% fewer
  schema-misalignment errors.
- **Huang et al. (ICLR 2024)** / **Kamoi et al. (TACL 2024)**: intrinsic self-correction weak
  without reliable external feedback — iterate on evidence, not on self-admonition.
- **Reflexion** (2023) / **Self-Refine** (2023): structured feedback iteration helps in the
  right settings (counterweight against over-blocking).
- **AgentBoard** (NeurIPS 2024) / **ToolSandbox** (NAACL 2025 Findings): progress-rate and
  stateful milestone evaluation — measure seconds-wasted, not loop counts.
- Ops precedent (finite retry budgets / circuit breakers): AWS Builders' Library, Azure
  Well-Architected.
