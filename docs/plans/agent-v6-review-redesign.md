# Work plan: Agent v6 — REVIEW redesign (verify/repair split, commit barrier)

**Status:** draft for review. **Date:** 2026-09-01. **Branch (when started):** `feature/agent-v6-review`.
**Sources:** trace review 2026-08-31→09-01 (448 traces, experiment `shlepa-traces`), three external
research reports on time-capped verification design (F2; kept in chat; references in §7), current
codebase state (verified in this repo), GitHub backlog.
**Companion plans:** `agent-v6-pipeline-hardening.md` (routing/handoff), `agent-v6-stagnation-guard.md`
(budget waste). This plan covers the third failure surface: the REVIEW phase itself.

---

## 1. Evidence base

### 1.1 What our telemetry says (trace review, 448 runs)

- **30% of runs end with the final LLM request aborted mid-stream at exactly the 45 s REVIEW cap**
  (request still in flight when the cap cut it).
- Solved: runs whose final request completes — **61%**; runs ending in an aborted final request —
  **17%** (44-point conditional gap; selection-biased, not a causal effect).
- Mathematical envelope if the whole gap were removable: `0.30 × (0.61 − 0.17)` = **+13.2 pt ceiling**
  (upper bound; overlaps the +13 pt plan-cap counterfactual — same capped cohort, do not add).
- In many aborted-final runs the reviewer was doing **new work** (continued searches/analysis) instead
  of verifying — the 45 s budget buys nothing.
- Worked example (`bench-ctf-whyos`, 0/14): PLAN ran its 60 s cap doing real analysis (22 LLM / 40
  tool calls) and found the key evidence; WORK was skipped (v5 routing); REVIEW saw the full PLAN
  transcript and the missing file, then — following "fix it NOW, write it best-effort" — resumed the
  analysis and was capped mid-search. `/app/flag.txt` never written → 0.
- Run shape (sep01): plan-capped **and** commit-capped runs solve **12%** (n=90).

### 1.2 What the research reports say (three reports, converging)

All three land on the same diagnosis: **REVIEW is not a weak verifier, it is an unrestricted agent
state where a capability boundary should be.** Their common skeleton:

1. **Who verifies.** Intrinsic self-verification without external feedback is unreliable (Huang ICLR'24:
   GPT-4-Turbo 91.5→90.0 GSM8K, Llama-2-70B 62→36.5 after self-correction; Kamoi TACL'24 survey).
   Mechanical oracles (tests, schema, format) beat model introspection (Agentless FSE'25; SWE-agent
   ACI; Aider lint/test loop; Self-Debug ICLR'24: +2–3 pt without tests vs **+12 pt with tests**;
   SWT-Bench: generated tests doubled SWE-agent fix precision). LLM semantic judgment is still
   needed where no oracle exists (LLM-as-judge >80% human agreement, but with self-preference/verbosity
   biases; Panickssery NeurIPS'24) — as a *bounded* judgment, not as the final authority.
2. **Preventing drift — structurally, not by prompt.** Production systems enforce capability
   boundaries and termination in the harness: Pydantic AI `FilteredToolset` (remove tools per step),
   LangGraph evaluator node + conditional END edge, AutoGen programmatic termination conditions,
   OpenAI Agents SDK history filtering, Claude Code plan-mode read-only permissions. No surveyed
   system relies on "you are only a reviewer" while `bash`/`edit`/`write` stay available.
3. **Split VERIFY from REPAIR.** Combined verify+repair works when feedback is crisp and external
   (Aider, SWE-agent, Self-Refine ~+20 pt on seven tasks) — and its gains vanish once repair cost is
   counted and feedback is self-generated (Olausson ICLR'24). Our final phase has neither property.
4. **Fresh curated context for VERIFY.** Cognition: clean-context reviewer catches ~2 bugs/PR, ~58%
   severe (Tier 3, no controlled ablation); Lost-in-the-Middle (TACL'24, incl. MPT-30B) and Du et al.
   (EMNLP'25: 13.9–85% degradation from input length alone) support removing the raw 40-call
   transcript; Cognition's own caveat: keep a communication bridge (intent/decisions), not amnesia.
5. **Early exit must be harness-side.** "checks passed → stop" in code, not in the prompt; OpenHands
   critic early-stopping (1.35 avg attempts vs 8) is the industrial analogue. A schema on
   `final_result` does not stop 40 s of tool calls *before* the JSON.
6. **Interrupt-safe final phase (anytime/best-so-far).** Zilberstein anytime algorithms; SWE-agent
   `attempt_autosubmission_after_error`; LangGraph checkpoint-per-step. The tool-less timeout salvage
   violates the invariant: it puts text in history, not on the only scored surface (disk).
7. **Budget sizing.** No published universal verify/execute ratio (Snell: difficulty-dependent
   adaptive allocation >4× best-of-N; COLM'25: generative verification up to 8× compute to match
   self-consistency). Design subcaps so no single request can occupy the whole phase; do not raise
   45 s (more time = more drift under an unknown kill).
8. **Confidence is not a gate.** Gemma-2-27B expressed-confidence AUROC 0.56 (JMIR'25); Qwen3-32B
   ECE 0.226 (NeurIPS'25); Xiong ICLR'24: verbalized confidence generally overconfident. Advisory
   feature only, after local calibration.

### 1.3 Verified code facts (this repo, v5)

- `phases/commit.py` (`CommitPhase`, id `commit`): REVIEW **continues the current conversation**
  (`trim_history(state.model.last_messages)`), has **all four tools** (`read/write/edit/bash`), typed
  output `ReviewResult` (status ok|partial, verdict done|next_round, artifact, checks[], hints[],
  notes[]), **terminal, never retried**, capped at `REVIEW_CAP` = 45 s.
- `prompts/commit.md` says: "If it is missing or broken: **fix it NOW. You have full tools
  (read/write/edit/bash)** — repair the file, write it best-effort if it does not exist" — drift is
  *authorized*, not merely permitted. It also says "After the checks pass, stop immediately" — an
  early-exit rule that exists only as prose (our models' instruction-following is the weakest layer).
- On the 45 s cap: `_run_phase` → `PhaseResult(status="timeout")` → `_pipeline` sees a terminal phase
  → **returns immediately**. REVIEW gets **no** `final_ask` — a REVIEW cap means the run ends exactly
  where the model was (mid-search, file possibly never written). This is the "aborted final" cohort.
- The tool-less `final_ask` (30 s cap) fires only on PLAN/WORK cap: `FINAL_ASK_MESSAGE` =
  "Write the final deliverable NOW … **Do not call any tools** … reply with one short line naming the
  deliverable path." Even stricter than the research brief assumed: it asks for a one-line path
  *narration*; the only way that text reaches disk is if REVIEW later converts it to a file — a
  model-mediated commit on the most time-pressured path we have.
- Harness already knows everything a pre-check needs: `WorkResult.deliverable` (declared path) is in
  `state.results`; the workdir is `deps.workdir`; existence/non-empty/`json.loads` are free.
- One agentic loop may occupy the whole 45 s (per-request wall is 180 s > phase cap) — no subcaps.
- `WorkResult.confidence` exists and is logged — usable for calibration studies, not gating.

### 1.4 Hypotheses to validate on OUR data (before any redesign ships)

- **H1 (drift is measurable).** In aborted-final runs, REVIEW contains ≥3 "exploratory" tool calls
  (grep/find/ls/cat on non-artifact paths, re-running analysis) — i.e. new work, not verification.
- **H2 (the file was fine, the window was wasted).** A significant share of aborted-final runs had a
  valid non-empty artifact on disk *before* the final request started; the 45 s was spent improving
  or re-deriving, not producing.
- **H3 (salvage text contains the answer).** In PLAN/WORK-timeout runs, the tool-less `final_ask`
  output (in history) often names the answer/path — meaning the model *knows* the deliverable but
  cannot persist it; harness-persisting that body is directly recoverable score.
- **H4 (loop is mostly one cycle).** `next_round` verdicts are rare on the clean-verify path; the
  review→new-cycle loop does not need to be preserved for many tasks — it mostly serves drift
  recovery, which we want to remove.

Method: replay over the 448 exported traces (`tmp/trace-export/`); classifier rules are the same
deterministic tier as the stagnation plan (exact paths, artifact-vs-non-artifact). Gating the whole
workstream: H1+H2 must be confirmed at material prevalence before Phase R2/R3 ship; H3 is
independently actionable (it only needs the salvage text + file absence).

**R1 census results (2026-09-02, 474 traces / 14 batches / 35B+27B, 100% correlated to MLflow
runs — full numbers in [`docs/analysis/2026-09-02-review-drift-census.md`](../analysis/2026-09-02-review-drift-census.md)):**
H1 **CONFIRMED** (76% of capped finals had tool activity in REVIEW; 33% pure exploratory drift),
H2 **PARTIAL** (37% of capped finals wrote files inside the cap; strict mtime check deferred to R5),
H3 **REJECTED as score lever** (only 3.8% of `final_ask` answers mention a path), H4 **CONFIRMED**
(1/474 `next_round` verdicts). The commit-capped cohort is 144/474 (30.4%) and solves at 22.2%
vs 59.7–64.5% clean — the redesign's target surface is real and large. R2/R3 gate: **passed**.

### 1.5 Official scoring constraints (2026-09-02, problem statement + public repo)

Source: the main-stage task statement and `SecureIntelligent/UniversalAgenticCompetitionPublic`
(README, `local_task/*/task.toml`). These constraints were not in the research brief and change
several design decisions.

- **Binary per task, 15 hidden tasks.** 0 is awarded when the automated check does not confirm a
correct solution, explicitly including: code did not run, wrong result, **execution stopped by
timeout**, or a crash. A correct file that is never checked because the container was killed first
is still 0. **The only path to a 1 is: correct artifact + the agent exiting normally before the
per-task limit.**
- **Each task has its own time AND token limits, and neither is communicated to the agent.**
`run.sh "<instruction>"` is the only input; env carries only `LOCAL_AGENT_MODEL` /
`OPENAI_BASE_URL` / `OPENAI_API_KEY`. Public sample tasks: `agent.timeout_sec` = 120 s (trivial
`hello-file`) to 600 s (medium `fix-sqli-*`, forensics). The agent operates blind against an
external kill clock.
- **v5 has no global clock and no token budget** (config.toml: "NO global hard stop, NO global
token budget" — usage logged for analysis only). Under the official rules this is a scoring
defect, not a dev detail: a fixed 60/120/45 s cap-cycle (225 s) structurally exceeds a 120 s task,
and a per-task token limit can kill requests mid-run with no internal warning.
- **Tie-breaks: fewer total tokens first, then less wall time.** Early exit (D1), the read-only
token-lean VERIFY (D2) and fresh context (D4) now directly move the ranking on ties; every wasted
cycle spends tie-break budget. This is a second, independent value of D1–D5 beyond solve rate.
- **"A partial deliverable scores better than nothing" (current `prompts/commit.md`) is FALSE
under binary scoring** — a wrong file scores exactly like no file. The line must be replaced with
binary framing (work item, not a code change yet).
- **SWE-style fix tasks ship in-environment regression tests** (public `fix-sqli-*`: reference
solutions "wait for the local service before running regression tests"). The oracle for that
class is a test command against the patched repo, not a single file — the deliverable is a *kind*
(file / test command / answer), not always a path.
- **Runtime facts:** `jq`, `python3`, `ripgrep` are APT-preinstalled in `secureintelligent/acp`;
no runtime dependency installs — D1–D5 stay stdlib + already-shipped deps only. `agent.py` is
overwritten by the runner with the canonical wrapper (the byte-identical rule is official).
- **Consequence — design rule: no mechanism may condition behavior on the (unknown) task limit.**
The agent sees its own elapsed clock, its own phase caps, and its own token usage — and it sees
observable endpoint failures (429/402/error storms). It does NOT see the deadline or the token
cap. All budget logic must use known quantities or observed signals. The strategy is "be fast
and always exit normally", never "estimate the deadline". Every second/token saved is (a) better
tie-break, (b) less chance the unknown kill lands on useful work, (c) earlier normal exit.
---

## 2. Diagnosis (what is missing, specifically)

REVIEW conflates five states — `ensure_artifact_exists`, `verify_mechanically`, `judge_semantics`,
`repair`, `terminate` — inside one 45 s agentic loop with full tools and a prompt that authorizes
repair. Concretely missing:

1. **Commit barrier.** No harness-side guarantee that a scoreable artifact exists before (or survives)
   the final phase; no mechanical pre-check; the only "salvage" is a tool-less narration that cannot
   touch disk.
2. **Capability separation.** No boundary between verifying and working: `bash` in a reviewer is a
   write/exploration tool. For our weak instruction-following models, prompt-only role separation is
   the least dependable layer (confirmed by our own 71%-of-27B PLAN-cap data: prose caps leak).
3. **Hard termination edge.** No harness-side "PASS → END"; the model decides whether to stop, after
   it has already spent whatever it spent.
4. **Kill-proof budget topology.** A single request can be in flight at second 45 doing work *and*
   deciding at once; the abort then erases the decision too.
5. **Context shaping.** VERIFY receives the full 40-call transcript, which both degrades retrieval
   (long-context evidence at our model scale) and keeps "continue what I was doing" salient.

---

## 3. Design decisions

**D1 — Commit barrier (harness pre-check + salvage route).** Before the commit phase the harness
runs a mechanical check on the declared deliverable path (`WorkResult.deliverable`, else
`ReviewResult.artifact` from the previous cycle): exists / non-empty / parses if extension is
`.json` / required top-level keys per the PLAN-emitted `artifact_spec` (deliverable kind
`file|test_command|answer`, path, format, keys — §1.5: the 15 hidden tasks cannot be pre-registered,
so the static family table is dev-calibration only; the test-command kind runs the task's own
regression suite, the strongest oracle available). If missing/failing → **SALVAGE route**:
write-only agent (tool: `write` only), ≤30 s, prompt = spec + the last `final_ask`/WORK text it can
recover from history, first permitted action is the write; after salvage the harness re-checks and
persists whatever body the salvage emitted (harness-side persistence: the salvage request returns
`final_result` with `artifact` + `body`; harness writes atomically if the model never did). A
passing check still routes to REVIEW — the LLM-free oracle early-exit is recorded as IDEA-1 in
§10 (deferred, not enabled).

**D2 — VERIFY is read-only.** `commit` becomes the verifier: tools `read` only (artifact content
preloaded into the prompt; `read` remains for spec/files it must consult), no `bash`, no `write`, no
`edit`. Output = existing `ReviewResult` + one field: `repair_scope: none | local | needs_next_round`
with named failing checks. On `done`/`partial`+no-local-repair-needed → harness terminates
immediately in code (early exit; no extra LLM call).

**D3 — REPAIR is a separate bounded state.** Only entered on `repair_scope == local` with a named
failure. Tools: `read`/`edit`/`write` on the deliverable only (no `bash` — a "failing test needs
investigation" routes to `needs_next_round`, not a debug loop). Budget: ≤1 mutation request. After
the mutation the harness re-runs the mechanical check; result recorded, run continues to verdict.
`needs_next_round` → `next_round` verdict with hints (new PLAN→WORK cycle) — the existing loop, now
reached by design instead of by drift. **No time gate (§1.5):** the per-task limit is invisible to
the agent, so a new round must NOT be conditioned on time — the trigger is the failed strict
check, full stop. The deliverable is already 0; a killed round is 0 either way; the only
difference is second-order tie-break tokens, which never outweighs a point. Under binary scoring
a failed strict check is the **only** justified trigger for a new round; "could be better" is
never (polish is worth 0).

**D4 — Fresh curated context for VERIFY.** The verifier sees: task spec + artifact content +
mechanical check results + compact decision/evidence summary (`WorkResult.summary/findings` or
`PlanResult.goal/findings` + last hints) — not the raw transcript. REPAIR keeps the continuation
context (it needs to know what was done). Counter-evidence respected: the summary IS the
"communication bridge" (Cognition) — never artifact-only.

**D5 — Subcaps inside the 45 s.** VERIFY ≤15 s / REPAIR ≤20 s / recheck+decide ≤10 s, each a
separate request, so the 45 s kill can never catch "work + decide" in one in-flight stream. These
are engineering subcaps (no published optimum), A/B-tunable; early exit overrides them (PASS at
second 12 ends at second 12). **No T-relative caps (§1.5):** the per-task limit is invisible to
the agent, so phase caps cannot be scaled to it — keep fixed caps. The T-free robustness is
total wall time: the trivial linear flow (PLAN → WORK → REVIEW on a file the instruction already
states) stays ≤ ~105 s (fits the smallest observed sample limit, 120 s), work-class tasks in the
public samples carry 600 s limits (assumption to flag, not a dependency), and every early exit
shortens the window in which the unknown kill can land on useful work.

**D6 — Confidence stays advisory.** Logged, never gates. Calibrate locally on our telemetry
(confidence vs reward, per model × task family) before any threshold discussion.

**D7 — Keep REVIEW as a separate phase.** Do not fold verification into WORK: error correlation
(self-grading own work) and the fresh-eyes signal (Cognition) argue for independence; the cost is
one bounded LLM pass, now hard-capped by D5. A/B decides if the pass earns its time.

**D8 — Interaction with the companion plans.** v6 pipeline (plan-timeout → WORK, strictly linear —
the plan→commit shortcut is removed, 2026-09-02) shrinks the plan-transcript-into-REVIEW path;
trivial tasks now flow PLAN → WORK → REVIEW, and the D1 salvage case is simply "file missing after
WORK". The stagnation guard's finalization reserve generalizes: when `remaining ≤ R`, the phase
enters FINALIZING (no new exploratory calls) — in REVIEW that coincides with D2. Impact envelopes
(+13 pt plan-cap, +13.2 pt aborted-final) cover the same cohort: report them as levers on one pool,
never summed.

---

## 4. Phases

### Phase R0 — Observability (shared prerequisite with pipeline plan Phase 0)

- **R0.1** Artifact lifecycle events: `deliverable_check` (path, exists, size, parse_ok, source of
  path) logged at every phase boundary; `time_to_first_valid_artifact` per run; `final_ask` gets a
  span (output value = the salvaged text — this is H3's data). **AC:** every exported trace carries
  one `deliverable_check` per boundary and a `final_ask` span with `output.value`.
- **R0.2** Fix `trace_digest` attribute keys (#68) and add `phase` attribute on tool spans —
  prerequisite for R1 and for the stagnation replay. **AC:** loop signal fires on the real span
  names; a synthetic 4×-identical-bash fixture is detected.

### Phase R1 — Offline validation on 448 traces (gate for R2–R4)

- **R1.1** Drift census per run: REVIEW tool calls split into verify-like (read of artifact, format
  checks) vs exploratory (non-artifact reads, search bash, re-analysis); aborted-final vs
  completed-final cohorts; by model and by task family. **AC:** report `tmp/analysis/review-drift.md`
  with H1/H2 verdicts and per-task-tables.
- **R1.2** Salvage audit: for PLAN/WORK-timeout runs, classify whether the `final_ask` text contains
  a usable answer/path (rule-based: path mention + non-empty body + file absent on disk at end).
  **AC:** H3 prevalence number with a 20-sample manual spot check.
- **R1.3** `next_round` census: frequency, what hints said, whether the next cycle solved it (H4).
  **AC:** numbers in the same report; feeds the decision on keeping the loop cheap.

### Phase R2 — Commit barrier (D1) — smallest, ships first

- **R2.1** `shlepa_agent/deliverable_check.py`: pure function `(workdir, path, family_spec)` →
  `{exists, non_empty, parse_ok, keys_ok, valid}` + `deliverable_check` event logging in the
  pipeline (before commit, after work, after salvage). **AC:** unit tests incl. missing/empty/
  corrupt-JSON/ok cases; event visible in a dev run.
- **R2.2** SALVAGE route: new write-only phase (≤30 s, `write` only) entered when the pre-commit
  check says missing; harness persists `final_result.body` atomically (tmp file + rename) if the
  model itself never wrote; re-check afterwards. Kill-switch `SHLEPA_SALVAGE=0`. **AC:** unit test
  (fake model emitting body, no write call) leaves a valid file on disk; dev run on a
  missing-artifact task writes the file; `shlepa smoke` green.
- **R2.3** ~~Oracle pass → immediate exit~~ — **DEFERRED (2026-09-02):** recorded as IDEA-1 in
  §10, not enabled in the current scope. The mechanical check always routes to REVIEW; there is no
  LLM-free early exit. Full spec (conditions, ground-truth anchor, safety argument) in §10.

### Phase R3 — VERIFY/REPAIR split (D2–D4)

- **R3.1** Tool allowlists: `[phases.commit].tools = ["read"]` in `config.toml`; new `repair` phase
  class (tools `read/edit/write`, no bash, ≤1 mutation request, no retry), entered only on
  `repair_scope=local`. `ReviewResult` gains `repair_scope` + per-check `pass` booleans (backward-
  compatible default `local`/empty). **AC:** unit test that a `bash` call in commit is rejected by
  the harness (not the prompt); repair on non-local scope is a no-op route to `next_round`.
- **R3.2** VERIFY prompt restructure (`prompts/commit.md`): reviewer role, no-repair mandate,
  artifact preloaded, explicit `checks[{name, pass, evidence}]` contract, "a check that cannot be
  run is `pass=false, evidence=unchecked`". REPAIR prompt (`prompts/repair.md`): named failure +
  "edit the file, do not investigate". **AC:** prompts pass the existing prompt-render tests;
  rendered VERIFY prompt contains the artifact content placeholder.
- **R3.3** Fresh curated context for VERIFY: build the review packet (spec + artifact + checks +
  summary) instead of `trim_history(last_messages)`. Keep full-context mode behind
  `SHLEPA_REVIEW_CTX=full|fresh` (A/B arms). **AC:** unit test on packet assembly (missing artifact
  → packet says so; summary truncation bound); both modes run in dev.
- **R3.4** Harness early exit: `ReviewResult` verdict `done`/`partial` with no local repair → end in
  code (already the case) PLUS mechanical-pass short-circuit from R2.3. **AC:** no extra LLM request
  after a harness-side pass (asserted in a dev run log).

### Phase R4 — Kill-proof budget topology (D5)

- **R4.1** Subcaps: VERIFY 15 s / REPAIR 20 s / recheck 10 s as separate requests under the 45 s
  envelope (env-overridable, `SHLEPA_REVIEW_SUBCAPS=0/1`). **AC:** unit test that a hung VERIFY
  request cannot consume the REPAIR budget; cap-exceeded in one sub-phase leaves the on-disk
  incumbent intact (anytime invariant: file from R2.2/WORK is never deleted by the phase).
- **R4.2** Remove the tool-less `final_ask` from the PLAN/WORK→commit path (replaced by R2.2
  salvage-with-write); keep the message only as history context for the salvage prompt. **AC:** a
  PLAN-timeout dev run ends with a file on disk whenever the answer was in context (checked on the
  whyos-class fixtures).

### Phase R5 — Experiments

- **R5.1** Mini A/B (27B, ~20 tasks): arms G0 (current v5) / G1 (R2 only) / G2 (R2+R3 fresh) /
  G3 (G2+R4). Metrics: aborted-final rate, time-to-verdict, solve rate, repair success (solved
  with repair vs without), false-done (mechanical check pass but reward 0).
  **AC:** decision memo with per-arm tables and the go/no-go for a 35B sweep.
- **R5.2** 35B full sweep of the winning arm vs current; gate: solve rate ≥ G0 (no regression on
  completed-final runs) and aborted-final rate materially down. **AC:** batch comparison in
  MLflow + memo; if `false-done` rate is non-zero, analyze the family (check coverage vs
  verifier) — that list gates IDEA-1 (§10) if oracle early-exit is ever enabled.

---

## 5. Impact estimate (scenario math, not forecast)

- Envelope: `0.30 × (0.61 − 0.17)` = **+13.2 pt** upper bound (the whole aborted-final gap).
- Sensitivity: converting fraction `r` of the gap → `+13.2 × r` pt; `r = 0.25–0.5` → **+3.3 to
  +6.6 pt**. Overlaps the pipeline plan's +13 pt plan-cap counterfactual (same capped cohort).
- IDEA-1 oracle early-exit (deferred, §10) would additionally *save* ~45 s of wall time per run it
  fires — under an unknown external kill, saved wall time is option value, not just tokens. Not
  counted in the scenario math above (idea, not scope).
- **Tie-break value (§1.5, unpriced):** early exit and the read-only/fresh-context VERIFY save
  wall time and input tokens on *solved* tasks — that is ranking on ties, plus penalty avoidance
  (no late-round token burn, no killed rounds). The scenario math above counts solve rate only;
  treat tie-break gains as free upside.
- What would change the verdict: R1 data showing drift is NOT the cause of the 44-pt gap (e.g. the
  gap is fully explained by task difficulty, not by REVIEW behavior), or R5.1 showing G2/G3 lose
  solve rate on completed-final runs (over-restriction). Both are instrumented, not speculative.

## 6. What we should NOT do

- **Do not just raise the 45 s cap.** No published universal verify/execute ratio; under an unknown
  kill, more time in an unrestricted reviewer buys more drift (Anthropic: agents continuing after
  enough evidence). If anything, subcaps (D5) shrink the effective window.
- **Do not do prompt-only role separation** ("you are only a reviewer") while `bash`/`edit`/
  `write` stay available. Our own data (71% PLAN-cap on 27B) shows prose constraints leak on these
  models; the affordance stays, the drift stays.
- **Do not gate on verbalized confidence.** Gemma-2-27B AUROC 0.56; Qwen3-32B ECE 0.226; nearest
  size-class evidence is too weak. Calibrate locally first (D6), if ever.
- **Do not equate format-valid with content-correct.** A parseable JSON is not a correct answer —
  the `false-done` metric in R5.1 exists to catch exactly this, and it gates IDEA-1 (§10) if the
  deferred oracle early-exit is ever enabled.
- **Do not force REPAIR on every objection.** `repair_scope` distinguishes `local` from
  `needs_next_round`; "I'm not sure" must remain a route to a new cycle, not a license to debug in
  the final window.
- **Do not discard the last good artifact while reviewing.** Writes stay append/atomic; phases never
  delete the incumbent; salvage persists, never erases (anytime invariant).
- **Do not buy a separate verifier model, a learned per-task time estimator, or any
  deadline-prediction machinery (§1.5).** The per-task limit is not visible to the agent; budget
  logic uses known quantities (phase caps, own elapsed, own token usage) or observed signals
  (endpoint errors) only.
- **Do not run unbounded test/debug loops in REVIEW.** Mechanical checks run in the harness with a
  fixed budget; agentic exploration stays in WORK.

## 7. Risks and counter-evidence

- **Strongest counter-evidence:** Self-Refine (~+20 pt avg), Self-Debug (up to +12 with tests),
  Aider and Devin's iterative loops — combined verify+repair can genuinely help. Our design does not
  ban repair; it *sequences* it (verify first, bounded repair on a named failure) and moves the
  exploratory kind of repair to `next_round`. If R5.1 shows G2 loses to G1, the split is rejected.
- **Fresh context backfire:** a contextless reviewer can reject deliberate choices (Cognition's own
  communication-bridge caveat). Mitigation: D4 packet includes the decision summary; `SHLEPA_REVIEW_CTX`
  keeps full context as an A/B arm, not a guess.
- **Over-restriction false negatives:** read-only VERIFY cannot catch "the file is valid but the
  right answer needs a quick `grep` in the corpus". If R1.1 shows verify-like checks that require
  non-artifact reads at material frequency, D2 gets a narrow `read`-only extension (still no bash).
- **Confounding:** the 17%/61% gap is observational; difficulty confounds it. That is why R1/R5 are
  A/B-based and the plan quotes only scenario math.
- **Zip/telemetry constraints:** salvage and subcaps live in the agent core (zip-safe, no new deps);
  `deliverable_check` expectations come from the PLAN `artifact_spec` (runtime, nothing committed
  for the hidden pool; the dev family table is calibration only); all new events go through the
  existing redacting logger.

## 8. References (research anchors from the three F2 reports; tiers as given)

- Huang et al., ICLR'24 (self-correction degrades; [1]); Kamoi et al., TACL'24 (intrinsic vs
  external feedback; [1]); Self-Refine, NeurIPS'23 (~+20 pt; [1]); Self-Debug, ICLR'24 (+2–3 w/o
  tests, +12 w/ tests; [1]); Olausson et al., ICLR'24 (cost-aware self-repair; [1]); Lightman/PRM,
  ICLR'24 ([1]); Setlur et al., ICML'25 (verifier scaling at 3B/8B/32B; [1]); Singhi et al.,
  COLM'25 (verification compute cost; [1]); Snell et al., 2024 (adaptive allocation; [4]).
- LLM-as-judge: Zheng et al., NeurIPS'23 (>80% agreement + biases; [1]); Panickssery et al.,
  NeurIPS'24 (self-preference; [1]); Wataoka et al., NeurIPS'24 workshop (self-preference; [1]);
  G-Eval, EMNLP'23 ([1]).
- Calibration: Tian et al., EMNLP'23 (verbalized confidence ~50% rel. ECE cut; [1]); Xiong et al.,
  ICLR'24 (overconfidence; [1]); Yoon et al., NeurIPS'25 (33/36 wins; Qwen3-32B ECE 0.226; [1]);
  Bentegeac et al., JMIR'25 (Gemma-2-27B AUROC 0.56; [1]); Yang/Tsai/Yamada, ICLR'25 ws (prompt
  dependence; [1]).
- Context: Liu et al., Lost in the Middle, TACL'24 (incl. MPT-30B; [1]); Du et al., EMNLP'25
  Findings (length-alone degradation 13.9–85%; [1]).
- Coding agents: Agentless, FSE'25 ([1]); SWE-agent, NeurIPS'24 ([1]) + `attempt_autosubmission_`
  `after_error` in source ([2]); SWT-Bench, NeurIPS'24 ([1]); Aider lint/test docs ([2]);
  OpenHands critic early-stopping 1.35 vs 8 ([3]); OpenHands SWE-bench harness ([2]).
- Production: Cognition "Multi-Agents: What's Actually Working" (clean reviewer ~2 bugs/PR, 58%
  severe; [3]); Anthropic "Building effective agents" ([3]) and "Multi-agent research system"
  (effort rules, continuation guardrails; [3]); Anthropic "Demystifying evals" (grader mix; [3]).
- Frameworks: Pydantic AI `FilteredToolset` ([2]); LangGraph evaluator-optimizer workflow +
  persistence ([2]); AutoGen termination conditions ([2]); OpenAI Agents SDK handoffs/history
  filtering ([2]); OpenAI Structured Outputs 93%→100% ([2]).
- Anytime/checkpoint: Zilberstein, AI Magazine'96 ([1]); Zilberstein & Russell, AI'96 ([1]);
  Challa et al., CS Review 2026 (survey, interruptible vs contract; [1]).

## 9. Cross-references

- `docs/plans/agent-v6-pipeline-hardening.md` — routing (plan timeout → WORK) removes the
  plan-transcript-into-REVIEW path; Phase 0 (telemetry fixes) is shared with R0.
- `docs/plans/agent-v6-stagnation-guard.md` — finalization reserve generalizes over all phases
  including REVIEW; `stalled_retry` also fires on repair loops; shared canonicalizer/ledger.
- Backlog: #68 (digest keys — R0.2), #35 (dangling runs — hygiene for the new phase events), #66
  (CI/test debt before A/B sweeps), #64 (in-image verification of any phase change).
- Ordering: R0 (shared) → R1 (gate) → R2 (smallest, ships first, independently valuable) → R3 →
  R4 → R5. R2 can ship even if R3/R4 are rejected.

## 10. Deferred ideas (recorded, not enabled)

Ideas we discussed, judged sound but deliberately out of scope for the current v6 work. Each keeps
its full spec here so re-enabling is a decision, not a re-investigation.

### IDEA-1 — Oracle early-exit (LLM-free "done" on exact-content tasks)

**Decision (2026-09-02):** recorded as an idea, not enabled. The post-work mechanical check
(`deliverable_check`) always routes to REVIEW in the current scope; trivial tasks flow linearly
PLAN → WORK → REVIEW like everything else.

**What it was:** if the pre-review mechanical check fully passes **and** the task's answer is fully
specified in the instruction text, the harness ends the run `done` in code — no LLM review at all
(log `commit=skipped_oracle`).

**Exact firing conditions (all required):**
1. `valid` — file exists, non-empty, parses (format per `artifact_spec`), all declared keys present.
2. `spec.kind == "answer"` (or a file whose content is fully specified).
3. `spec.expected_content` is a **verbatim substring of the instruction text** — the ground-truth
   anchor. `artifact_spec` is model-emitted in PLAN, so this harness-side guard makes the oracle
   unfakeable: a fabricated or mis-extracted expected value fails the substring check and the run
   falls through to normal REVIEW.
4. `normalized_file_content == normalized_expected_content` (minimal normalization: trailing
   whitespace/newline only; no case-folding).

**When it exists:** only for exact-content tasks (hello-file class: the instruction states the
exact file content). Explicitly NOT an oracle: in-environment test-suite pass (hidden verifier may
check more — SWE-bench mechanics), format-only files (parseable JSON ≠ correct answer), and
answers derivable but not stated (the harness stays a pure file-vs-spec function; it does not
compute answers).

**Safety:** false "done" is impossible by construction (file vs ground truth from the input text,
zero LLM judgment); the only failure mode is a miss, which costs tie-break speed on a trivial
task and nothing else. Residual edge: verifier whitespace strictness vs minimal normalization —
covered by the A/B easy control (hello-file must stay 100%).

**Role and value:** in the linear pipeline this was the fast path replacing the v5 `plan→commit`
shortcut — trivial tasks (~PLAN 5–10 s + WORK ~10 s) would exit at the mechanical check with no
model in the exit loop. Frequency estimate for a 15-task hidden pool: 0–3 tasks (public sample:
the trivial class). Value: deterministic trivial class, tie-break savings (shortest run, no review
tokens), and validation of the check machinery that powers routing/salvage either way.

**Re-enablement gate:** `false-done` rate from R5 is zero on exact-content families, and the
substring anchor + normalization are unit-tested (a missed oracle is free; a false done is the
only thing that must never happen).
