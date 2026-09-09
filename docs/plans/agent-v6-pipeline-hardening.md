# Work plan: Agent v6 — pipeline hardening

**Status:** draft for review. **Date:** 2026-09-01. **Branch (when started):** `feature/agent-v6-pipeline`.
**Sources:** trace review 2026-08-31→09-01 (448 traces, experiment `shlepa-traces`), three external
research reports on plan/execute boundary enforcement (kept in chat; references in §9), current
codebase state (verified in this repo), GitHub backlog.

---

## 1. Evidence base

### 1.1 What our telemetry says (trace review)

Solved: 35B **51%** (186/362), 27B **41%** (28/67); n≈12–14 per task.

Run shape (sep01, n=319) and solve rate:

| shape | n | solved |
|---|---|---|
| 3 groups, clean plan, clean commit | 159 | 69% |
| plan capped, commit clean | 42 | 33% |
| plan capped **and** commit capped | 90 | **12%** |
| trivial plan→commit shortcut | 10 | 100% |

- PLAN cap (60 s) hit in **42%** of runs (31% on 35B, **71% on 27B**); capped plans make 40+ tool
  calls of real work — the model executes in a "do NOT start working" phase.
- On PLAN timeout the pipeline goes `plan → final_ask (tool-less, impossible instruction) → commit`,
  **skipping the 120 s WORK phase entirely**.
- Final request aborted at the 45 s REVIEW cap → **17%** solved vs **61%** clean.
- Counterfactual ceiling: if the 132 plan-capped runs solved at the clean rate, overall ≈ **+13 pt**
  (upper bound; the cohort is selection-biased toward hard tasks).
- Worked example (`bench-ctf-whyos`, 0/14): key evidence (the `key=`/`mac=` URL family) was found
  during PLAN; REVIEW kept analyzing instead of writing `/app/flag.txt` → 0.
- The whole SOC "detection" family (dns-tunnel, proc-hollow, rdp-ptt, https-beacon, aws-passrole,
  dll-hijack) is a score wall at 0–1%: the agent finds evidence but never converges on the expected
  answer format.
- Telemetry defects: `trace_digest` loop/repeated signals broken (wrong attribute keys); root span
  has no inputs/outputs (MLflow scorers unusable); `final_ask` leaves no span; one dangling RUNNING
  MLflow run after an OOM-killed container (137).

### 1.2 What the research reports say (three reports, converging)

All three independently land on the same ranking (their common skeleton, with evidence pointers):

1. **The boundary must be enforced by the harness, not the prompt.** Claude Code plan mode
   (read-only permission mode + `ExitPlanMode`), Cline plan/act (mode rebuild; documented leaks when
   enforcement was incomplete or a shell escape existed — issues #4387, #13586), Roo Code
   (`isToolAllowedForMode`), OpenHands planning example (planner gets `Glob`/`Grep` + a `PLAN.md`-only
   editor; executor is a fresh conversation). Mechanism is model-independent → transfers **high** to
   our 27–35 B models.
2. **No PLAN termination may delete WORK.** No surveyed system routes "unfinished planner →
   verifier, skipping executor". Our `plan timeout → commit` transition is the singular defect.
3. **Hand-off: fresh WORK + compact structured state + recoverable raw evidence.** Not "plan JSON
   only" (lossy — Cognition: actions carry implicit decisions) and not "carry the 40-tool transcript"
   (Lost-in-the-Middle TACL; Chroma Context Rot includes **Qwen3-32B**; CAT 2026: 32 B ReAct degrades
   53.2→48.8 from 150→500 steps while threshold compression stays flat; ReSum +4.5 pt; AgentFold
   30B-A3B warns fixed summarization can lose critical details).
4. **Repurpose the tool-less timeout call as a serializer**, not an impossible "write the file"
   instruction.
5. **Do NOT:** prompt-only enforcement; keep `bash` in PLAN (shell is a write tool); dump the full
   PLAN transcript into WORK; budget carry-over as the main fix (zero unused time on exactly the
   capped cohort); treat +13 pt as an expected gain (it is the ceiling).
6. Budget visibility can help (Budget-Aware Tool Use: 36.8→55.4 on SWE-bench Verified with a
   Budget Tracker) but that is frontier-model evidence — medium transfer; structural fixes come first.

Estimated impact (their sensitivity method, **our inference, not a benchmark**): hard-gated short
PLAN + guaranteed WORK plausibly recovers **50–75%** of the 18.7%→69% cohort gap ⇒ **≈ +6.5–9.8 pt
overall** on the 35 B full sweep; routing-only ≈ +3.3–6.5 pt.

### 1.3 Current state (verified in code)

| fact | where |
|---|---|
| `PLAN` has **all four tools**: `[phases.plan].tools = ["read","write","edit","bash"]` | `agent/shlepa_agent/config.toml` |
| Caps: plan 60 / work 120 / review 45 / bash 30 / llm wall 180 (fixed constants) | `agent/shlepa_agent/budget.py` |
| Routing: any non-terminal timeout → `_final_ask` (tool-less, "write the deliverable now", 30 s) → **`commit`** for BOTH plan and work timeouts; plan/work **error** also → `commit`; only `decision="commit"` (trivial) → `commit` is intentional | `agent/shlepa_agent/runner.py::_pipeline` |
| `_final_ask` reuses the same conversation (`trim_history(model.last_messages)`), no span, free text | `agent/shlepa_agent/runner.py::_final_ask` |
| WORK is a **fresh** conversation; plan arrives as rendered JSON in `previous_results`; PLAN has no scratch-write contract in the prompt beyond "write is for scratch notes under /tmp only" | `agent/shlepa_agent/phases/work.py`, `prompts/plan.md` |
| REVIEW continues the current (trimmed) conversation — on the plan-timeout path it inherits the **PLAN exploration transcript** with full tools | `agent/shlepa_agent/phases/commit.py` |
| `tools/recon.py` (884 lines, zero-dep, deterministic, ≤8 KB JSON) is **read-only** (verified: only file reads; no writes/subprocess) — currently reachable in PLAN only via `bash` | `agent/tools/recon.py` |
| Env overrides exist but **do not cover** phase tool lists or plan/work time (only commit time, bash, read, temp, max_steps, budgets) | `agent/shlepa_agent/config.py`, `docs/agent-config.md` |
| `log_task_to_mlflow` creates the run, logs metrics, **then** `set_terminated(FINISHED)` with no `finally` — any exception mid-function (artifact upload, trace wait) leaves a dangling RUNNING run | `cli/shlepa_cli/run_engine.py::log_task_to_mlflow` |
| Digest loop detector reads `tool.call.arguments` / `tool.call.result`; real spans carry `tool.parameters` / `output.value` (and `gen_ai.tool.call.*`) — verified in exported traces, so `loop:*` = false positives and `repeated_results` can never fire | `cli/shlepa_cli/trace_digest.py` vs `tmp/trace-export/*/traces/*.json` |
| Root span `agent.run` carries `task`, `shlepa.batch_id`, `git.commit`, cumulative tokens — **no input/output** → MLflow `Correctness`/`Safety` scorers fail ("requires inputs, outputs") | `agent/shlepa_agent/telemetry/__init__.py` |
| Agent has unit-test infra incl. `tests/test_runner.py`, `tests/test_phases.py`, `tests/test_recon.py` | `agent/tests/` |
| Backlog already holds most of this: **#69** route plan timeout→work, **#70** root-span inputs/outputs, **#68** digest keys, **#35** close dangling runs, **#72** phase-id span labels, **#73/#74/#71** token/cache metrics, **#36** whyos/tablez/forensics analysis, **#66** host-engine stub tests broken by v5 rewrite, **#54** code_search (smart-grep) tool, **#64** ACP image re-verification (in progress on `feature/agent-v5-pipeline`) | GitHub issues |

---

## 2. Target design (v6)

Regime: **PLAN 30 s (read+recon only) → WORK 120 s (all tools) → REVIEW 45 s (all tools)**, cycles on
`next_round` as today. Invariant (the heart of v6):

> **Every PLAN outcome — success, timeout, or error — reaches WORK.** The pipeline is strictly
> linear (2026-09-02 decision: the `decision="commit"` plan→commit shortcut is removed) — every
> task, trivial ones included, flows PLAN → WORK → REVIEW. WORK is an untouchable execution
> reserve: no earlier phase may consume or skip it.

Exit routes (v5 → v6):

| PLAN outcome | v5 | v6 |
|---|---|---|
| done, `decision="work"` | WORK | WORK (unchanged) |
| done, `decision="commit"` (trivial) | REVIEW | **WORK** (shortcut removed; trivial tasks flow linearly) |
| **timeout** | final_ask → REVIEW | **final_ask = PARTIAL_HANDOFF → WORK** |
| **error** (after retries) | REVIEW | **WORK** (no plan; "execute directly" note) |
| WORK timeout | final_ask → REVIEW | unchanged |
| WORK error | REVIEW | unchanged |

Hand-off contract on plan timeout (harness-owned, not model-owned):

1. The 30 s tool-less `final_ask` is re-pointed: "emit a `partial_handoff` JSON" (typed
   `PartialHandoff` pydantic model via `final_result`, same pattern as phase outputs):
   `objective`, `findings[]` (fact + evidence location), `files_seen[]`, `hypotheses[]`,
   `failed_paths[]`, `next_action`, `deliverable_path_if_known`.
2. Independently of the model's answer, the harness appends a **deterministic `LAST_TOOLS` block**:
   the last N=6 tool calls from the PLAN conversation (name + args ≤200 chars + result ≤400 chars),
   extracted from `model.last_messages`. Key evidence survives even when the summary is weak (the
   whyos case: the `key=`/`mac=` URL family is a tool *result*, not plan text).
3. WORK starts **fresh** with: task + (partial plan JSON if present) + `partial_handoff` JSON +
   `LAST_TOOLS` block + explicit instruction: "the hand-off may be incomplete; first priority is to
   create/update the deliverable file on disk early and keep it fresh."
   The full PLAN transcript is **never** carried into WORK (context-rot evidence, §1.2.3); it stays
   on disk in the trace for post-hoc analysis.

Tools per phase:

| phase | v5 tools | v6 tools |
|---|---|---|
| plan | read, write, edit, bash | **read, recon** (new dedicated tool) |
| work | read, write, edit, bash | read, write, edit, bash, recon |
| commit (review) | all four | unchanged |

`recon` = thin tool wrapping `tools/recon.py` (already read-only, deterministic, ≤8 KB, 25 s per-call
cap inside the tool). It is structurally non-mutating, unlike `bash`. PLAN's prompt drops the
"scratch notes via write" line and the "run tools/recon.py via bash" line (it becomes the `recon`
tool). If A/B shows reconnaissance quality collapses (WORK re-does expensive discovery), the
follow-up is a *second* narrow probe tool (e.g. read-only `grep`/`find` wrapper) — **not** restoring
`bash` to PLAN.

Budgets: PLAN_CAP 60→**30** in `budget.py` (A/B knobs 20/30/45). WORK 120, REVIEW 45 unchanged.
Budget carry-over: **out of scope** (zero unused time on the capped cohort; revisit later).

### A/B scaffolding (enables the experiment matrix, §4)

- New env overrides in `config.py` (same pattern as existing `SHLEPA_*`):
  `SHLEPA_PLAN_TIME`, `SHLEPA_WORK_TIME`, `SHLEPA_PLAN_TOOLS` (csv),
  `SHLEPA_ROUTE_PLAN_TIMEOUT` (`work`|`commit`), `SHLEPA_HANDOFF` (`partial`|`off`),
  `SHLEPA_LAST_TOOLS_N` (int). All default to v6 values; `SHLEPA_ROUTE_PLAN_TIMEOUT=commit`
  + `SHLEPA_HANDOFF=off` reproduces v5 exactly for the baseline arm.
- MLflow: `log_task_to_mlflow` gets an `arm` tag (passed through `run_preset`); `SLEPA_PRESET`
  already tags traces, so arm = separate preset invocation.
- Mini preset `experiments/v6-mini.yaml`: ~11 tasks covering the failure modes —
  `bench-ctf-whyos`, `bench-ctf-tablez`, `contest-incident-log-forensics`,
  `bench-soc-{dns-tunnel-a,proc-hollow-a,rdp-ptt-a,https-beacon-a,aws-passrole-a}`,
  `contest-fix-sqli-search`, `bench-cve-bench-cve-2771` (token hog control),
  `contest-hello-file` (easy control).

---

## 3. Work items

### Phase 0 — observability first (so the v6 effect is measurable)

Order matters: without the F3/F4 fixes we cannot distinguish "v6 helped" from "the measurement
moved". All items are dev-only; the agent base env gains **no** otel dependencies.

| # | item | files | AC |
|---|---|---|---|
| 0.1 | Fix digest signal keys (issue **#68**): args → `tool.parameters` (fallback `gen_ai.tool.call.arguments`, keep `tool.call.arguments`), result → `output.value` (fallback `gen_ai.tool.call.result`); unit tests incl. a synthetic trace with a real 4× identical-bash loop (must fire) and 4× different-arg calls (must not) | `cli/shlepa_cli/trace_digest.py`, `cli/tests/test_trace_digest.py` | On the already-exported `tmp/trace-export/*` traces: `loop:*`/`repeated_results:*` signals change from 256/0 to the true values (expected ≈0/0 given the review found zero true loops) |
| 0.2 | Root span inputs/outputs (issue **#70**): input = task prompt, output = final deliverable content/answer; set on `agent.run` in `telemetry/__init__.py` (the runner already returns the final output — thread it into the span end) | `agent/shlepa_agent/telemetry/__init__.py`, `agent/shlepa_agent/runner.py`, `agent/shlepa_agent/__main__.py` | After a dev run with `SLEPA_OTEL_ENABLED=1`, `mcp_mlflow_evaluate_traces` `Correctness` scorer runs without the "requires inputs, outputs" error on a fresh trace |
| 0.3 | Phase-id labels on agent spans (issue **#72**): `phase` attribute on phase spans (plan/work/commit) — cheap, unlocks per-phase token slicing in traces | `agent/shlepa_agent/runner.py`, `telemetry/__init__.py` | Span in Jaeger/MLflow carries `shlepa.phase`; digest can split per-phase tokens |
| 0.4 | Span for `final_ask` (F2 silent gap): it is a model request — ensure the instrumented path emits an LLM span (it currently doesn't) | `agent/shlepa_agent/runner.py::_final_ask` | The whyos-type silent 13 s gap no longer exists in traces |

### Phase 1 — A/B scaffolding

| # | item | files | AC |
|---|---|---|---|
| 1.1 | Env overrides from §2 (plan/work time, plan tools csv, routing mode, handoff mode, last-tools N) + `docs/agent-config.md` table rows + unit tests (config parsing) | `agent/shlepa_agent/config.py`, `agent/tests/`, `docs/agent-config.md` | `SHLEPA_ROUTE_PLAN_TIMEOUT=commit SHLEPA_HANDOFF=off` ⇒ pipeline behavior identical to v5 (verified by a routing unit test + one smoke run) |
| 1.2 | `arm` tag in MLflow runs (thread from CLI) | `cli/shlepa_cli/run_engine.py`, `cli/tests/test_run_engine_batch.py` | Runs of an A/B arm filterable by `tags.arm = '<arm>'` |
| 1.3 | `experiments/v6-mini.yaml` mini preset | `experiments/` | `shlepa run v6-mini --dry-run` lists the 11 tasks |

### Phase 2 — v6 pipeline (the core)

| # | item | files | AC |
|---|---|---|---|
| 2.1 | New `recon` tool wrapping `tools/recon.py` (25 s cap, ≤8 KB output, read-only by construction); registered in `ALL_TOOLS`; unit test | `agent/shlepa_agent/tools/recon_tool.py` (new), `tools/__init__.py`, `agent/tests/` | Tool callable from a phase with `tools=["recon"]`; returns JSON; no file writes (assert) |
| 2.2 | PLAN gating: `[phases.plan].tools = ["read","recon","search"]`; `PLAN_CAP = 30.0`; plan prompt: drop scratch-write line, recon via tool, **drop `decision` from `PlanResult` (linear pipeline — no plan→commit shortcut)** | `config.toml`, `budget.py`, `prompts/plan.md`, `phases/plan.py`, `outputs.py` | Config test: plan tool list = {read, recon, search}; a plan-phase attempt to call `bash` is refused by the tool surface (no tool exposed); routing test: a trivial PLAN lands in WORK, not REVIEW |
| 2.2a | `search` tool (grep/glob/ls over the task dir, stdlib-only, read-only by construction, ≤8 KB capped output with total match count); registered in `ALL_TOOLS` | `agent/shlepa_agent/tools/search_tool.py` (new), `tools/__init__.py`, `agent/tests/` | Unit tests: grep/glob/ls modes; cap + total-count output; no write side effects (assert) |
| 2.3 | Routing invariant: plan **timeout** → `final_ask(PARTIAL_HANDOFF)` → **WORK**; plan **error** → **WORK** (direct-execution note). Unit tests for `_pipeline` with stub phases (extend `tests/test_runner.py`) | `agent/shlepa_agent/runner.py`, `agent/tests/test_runner.py` | Table-driven routing tests: all 6 PLAN/WORK outcomes land on the v6 routes from §2 |
| 2.4 | `PartialHandoff` output model + typed final_ask on plan timeout + deterministic `LAST_TOOLS` extraction from `model.last_messages` (N=6, args ≤200, result ≤400) + WORK prompt block for handoff/last-tools ("may be incomplete; write deliverable early") | `agent/shlepa_agent/outputs.py`, `runner.py`, `phases/work.py`, `prompts/work.md` | Unit test: a stubbed timed-out plan conversation yields a WORK user message containing both the handoff JSON and the last tool results; `SHLEPA_HANDOFF=off` yields v5 behavior |
| 2.5 | WORK gains `recon` tool; `config.toml` `[phases.work].tools` | `config.toml` | — |
| 2.6 | Doc updates: `docs/agent-config.md` (regime table 30/120/45, invariants, A/B knobs), `README.md` pipeline paragraph | `docs/`, `README.md` | No stale "60 s plan" claims anywhere |

Non-goals of v6: merging PLAN+WORK into one phase (keep as a later A/B challenger), REVIEW prompt
rework, SOC-family task changes, model changes, per-task time estimation.

### Phase 3 — experiments (the point of all of the above)

1. **Mini A/B** (per §4 matrix), 35B, n=1 per task per arm, 4 arms → 44 runs ≈ 4 h.
   Gate: if A2/A3 show *lower* overall or regress the clean shape, stop and analyze digests before
   scaling.
2. **Full sweep** (35 B, `all.yaml`): winner arm vs A0 baseline, n=1 (34 runs ≈ 2.5 h each).
3. **Stability**: winner arm n=3 on the 11-task mini set (distinguishes noise from signal).
4. **27B check**: winner arm vs v5 on the mini set, 27B, n=1 (the 71% plan-cap-hit cohort).

Success criteria (35B full sweep, vs A0):
- **Primary:** overall solved +6…+10 pt (research sensitivity range; +13 pt = ceiling).
- **Mechanism:** plan-cap-hit rate drops or the capped cohort's solve rate rises ≥ +20 pt
  (12%→≥32%); double-capped shape (n≈90/319 in v5) → 0 by construction on the timeout path.
- **No regression:** clean 3-phase shape solve rate ≥ 65%; easy controls (hello-file) stay 100%.
- **Secondary:** plan-phase tokens drop (gating), work-phase time-to-first-deliverable-write drops.

### Phase 4 — hygiene & follow-ups (parallel, lower priority)

| # | item | issue | notes |
|---|---|---|---|
| 4.1 | Close dangling MLflow runs: `finally: set_terminated(run_id, "FAILED")` in `log_task_to_mlflow` + post-batch sweep that ends RUNNING runs of the batch and flags tasks with no linked trace; document: no two concurrent `shlepa run` batches on one box (OOM-137 source) | **#35** | `cli/shlepa_cli/run_engine.py` |
| 4.2 | Fix host-engine stub tests broken by v5 rewrite | **#66** | must be green before v6 lands on `dev` |
| 4.3 | SOC detection family: analyze 2–3 unsolved SOC task specs (expected answer format vs what the agent produces) via trace export; then an agent-side fix candidate (answer-format convergence step in REVIEW prompt, or task-agnostic "expected schema" reminder) — task files stay untouched | new (from #36) | separate branch; needs its own mini A/B |
| 4.4 | 27B + smart-grep re-measurement (n≥5/task) after v6 lands | **#58**, #54 | F6: +4 pt on n=1 is noise |
| 4.5 | ACP image re-verification of the final v6 build before the next submission | **#64** | depends on the active `agent-v5-hardening` plan finishing; then `shlepa submit-test` |
| 4.6 | Optional: budget-visibility prompt line (remaining phase time in the status header) as a later A/B — frontier evidence only, medium transfer | new if wanted | research report 3, ref [19] |

---

## 4. Experiment matrix (Phase 3)

| arm | env overrides | hypothesis |
|---|---|---|
| **A0 baseline** | `SHLEPA_ROUTE_PLAN_TIMEOUT=commit SHLEPA_HANDOFF=off SHLEPA_PLAN_TIME=60 SHLEPA_PLAN_TOOLS=read,write,edit,bash` (= v5 byte-identical behavior) | reference |
| **A1 routing-only** | `SHLEPA_ROUTE_PLAN_TIMEOUT=work SHLEPA_HANDOFF=off` (v5 tools, v5 60 s cap) | isolates the routing fix (issue #69 alone) |
| **A2 routing+gating** | A1 + `SHLEPA_PLAN_TIME=30 SHLEPA_PLAN_TOOLS=read,recon` | isolates the capability boundary |
| **A3 = v6 full** | A2 + `SHLEPA_HANDOFF=partial` | full package |

Arms run sequentially on the same box (no concurrent batches — OOM). Each arm = one
`shlepa run <preset>` with `SLEPA_OTEL_ENABLED=1`; analysis via `shlepa trace-export --batch` +
manifest/digests (post Phase 0, loop/repeated signals are trustworthy again).

## 5. Risks and counter-evidence

- **Reconnaissance too short / read-only too weak** (strongest counter): on forensics tasks the
  decisive probes (unpacking, 23 MB log mining) need execution. Mitigation: WORK always runs and
  re-does discovery; if mini A/B shows WORK repeating PLAN's discovery, add a second narrow
  read-only probe tool (grep/find wrapper), never raw `bash`. This is the research-flagged failure
  mode of ranking #1.
- **Lossy hand-off** (Cognition): a weak 27B summary can drop the one fact that matters.
  Mitigation: `LAST_TOOLS` deterministic block (harness, not model) + disk-re-readable evidence;
  monitor in digests "WORK repeats already-completed searches".
- **Trivial tasks under the linear pipeline**: with the shortcut removed, trivial tasks spend a
  few extra seconds in WORK before REVIEW. Acceptable (total wall time stays well under the
  smallest observed 120 s limit); monitor hello-file/bye-file solve rate + duration per arm —
  must stay 100%. The LLM-free oracle early-exit that would have kept them fast is recorded as a
  deferred idea (IDEA-1 in the review-redesign plan, §10) — not enabled.
- **Selection bias in the +13 pt ceiling**: capped runs are the hard tasks; treat +6.5–9.8 pt as a
  scenario range, not a promise. The mini A/B is the de-biasing step.
- **Measurement confound**: v5→v6 changes telemetry simultaneously (Phase 0). Mitigation: A0 runs
  in the *new* harness (env-overridden v5), so all arms share one measurement stack.
- **What would change the verdict:** mini A/B showing A1 ≥ A2 (gating hurts) → ship routing-only,
  keep PLAN with bash and a stronger prompt; A3 ≪ A2 → drop the typed handoff, keep `LAST_TOOLS`.

## 6. What we will NOT do (per research, agreed constraints)

- No prompt-only "don't execute" reinforcement with all four tools kept (Cline leak history).
- No raw `bash` in PLAN, no "read-only shell" half-measures (shell is a write tool).
- No carrying the full 40-tool PLAN transcript into WORK by default.
- No budget carry-over as a fix; no raising the PLAN cap as a first move.
- No REVIEW-as-emergency-executor changes in v6; no per-task time estimation; no model changes.
- No changes to `agent/agent.py` (byte-identical baseline), no otel deps in agent base env,
  no telemetry in the submission zip, zip ≤10 MB, no direct push to `main`/`dev`.

## 7. Sequencing & effort

| phase | rough effort | depends on |
|---|---|---|
| 0 (observability) | 0.5–1 d | — |
| 1 (scaffolding) | 0.5 d | — (parallel with 0) |
| 2 (v6 core) | 1–2 d | 1 |
| 3 (experiments) | 1 d machine-time + analysis | 0, 2 |
| 4 (hygiene/follow-ups) | 1–2 d, parallel | mostly independent |

Before any PR: `shlepa smoke` + `shlepa zip` pass; `agent` test suite green (incl. #66 fix if it
lands in the same PR window). Commits: Conventional, one logical change
(`feat(agent): …`, `fix(cli): …`, `test(agent): …`).

## 8. Open questions (decide before Phase 2, not after)

1. PLAN cap default: 30 s (proposal) vs 20 s — recon.py on a live target can take up to the bash
   cap; measure recon wall-time on the 3 live-target tasks first.
2. ~~`decision="commit"` trivial path~~ — **resolved (2026-09-02): removed.** The pipeline is
   strictly linear (PLAN → WORK → REVIEW); trivial tasks flow through WORK and exit via REVIEW.
   The LLM-free oracle early-exit is deferred (IDEA-1, review-redesign plan §10), not enabled.
3. `LAST_TOOLS` N and truncation (6 / 200 / 400 proposal) — size vs context-rot trade-off.
4. Should WORK-timeout `final_ask` also switch from "write the deliverable now" (impossible, no
   tools) to a state summary? Low value (REVIEW inherits the transcript) — defer.

## 9. References

Internal:
- Trace review 2026-08-31→09-01 (448 traces; F1–F6; data in `tmp/trace-export/`, `runs.json`).
- Issues: #68 #69 #70 #72 #35 #36 #66 #54 #58 #64 (backlog).
- Code: `agent/shlepa_agent/{runner.py,budget.py,config.toml,phases/,outputs.py,tools/}`,
  `cli/shlepa_cli/{run_engine.py,trace_digest.py}`, `agent/shlepa_agent/telemetry/`.

Research reports (three independent LLM analyses, same prompt; key external sources):
- Claude Code permission modes / `ExitPlanMode`; Cline `plan-and-act` docs + `mode.ts` + issues
  #4387/#13586 (leaks, shell escape); Roo Code `using-modes.md` / `switch-mode.md`
  (`isToolAllowedForMode`); OpenHands planning-agent example (`docs.openhands.dev/sdk/guides/agent-custom`).
- Agentless (FSE 2025, localization→repair artifacts); ReWOO (planner decoupled from observations);
  Plan-and-Solve (ACL 2023); SWE-agent ACI ablation (+10.7 pt); LangGraph plan-and-execute.
- Context: Lost-in-the-Middle (TACL 2024); Chroma Context Rot (2025, incl. Qwen3-32B); CAT
  "Context as a Tool" (ACL 2026 Findings, 32 B: 49.8/53.8/57.6); ReSum (+4.5 pt); AgentFold
  (ICLR 2026, 30B-A3B); LongMemEval (~30% long-history drop).
- Industry: Cognition "Don't Build Multi-Agents" (2025) + follow-up (2026, clean-context review,
  sub-frontier primary caveat); Anthropic multi-agent research post (90.2% internal eval),
  context-engineering and long-running-harness posts (structured handoffs, progress artifacts).
- Budget: Budget-Aware Tool Use (36.8→55.4 SWE-bench Verified, Budget Tracker, frontier models —
  medium transfer); BAGEN (budget awareness r≈0.35, weak models worse).
