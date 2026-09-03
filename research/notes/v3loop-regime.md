# The v3 Loop Regime: a Budgeted main → commit Loop as a Selectable Regime

- **Category:** agent-architecture (regime design / budgeting)
- **Source:** user decision 2026-09-04; implementation commits `56a1c17` (agent
  pipeline), `ca4327d` (dispatch + CLI)
- **Reviewed:** 2026-09-04

The v3 agent (MLflow model version 3, run `ee78c24c`) had the best
control-flow behaviour we had: one open main loop against a *depleting*
budget, with a single terminal commit on budget breach. The v5 rewrite
traded that for the plan → work → review cycle with fixed per-phase caps
and no budget. This note records the decision to bring the v3 control
flow back **as a selectable regime** — without reverting v5 — so both
pipelines can be A/B tested against the same task set, toolsets and
models.

## Decision

`[agent].loop` (`SHLEPA_LOOP` env, `shlepa run --loop`) selects the regime:

- `cycles` (default) — the v5 plan → work → review pipeline (`runner.py`),
  unchanged.
- `v3` — the budgeted single-loop regime (`agent/shlepa_agent/v3loop.py`):
  one free-text `main` phase bounded by the `[v3loop]` budget, then a
  terminal `commit` on breach.

The loop axis is **orthogonal to the toolset arm** (`AGENT_TOOLSET`): any
arm (baseline / +smart-grep / +sifs / +forensics / +mitre-kb / +recon /
read-only) runs under either regime. A/B = one flag per run, tagged
`loop=v3` on the MLflow run (v3 only; cycles is the default and carries
no tag, mirroring the `toolset` tag convention).

## Key design points

- **The v3 budget is consumable and enforced** (`[v3loop]`, defaults from
  the registered v3 agent): `soft_time` 500s / `hard_time` 585s wall gates
  checked before every LLM request (`BudgetedModel`; soft fires first),
  `request_limit` 90 (checked before each request) and `token_budget`
  300k (checked after each response) via pydantic-ai `UsageLimits`,
  `request_wall` 240s per-request wall. hard 585s + `commit_time_cap` 80s
  stays under the 600s task limit.
- **Commit only on budget breach** (soft/hard wall, request limit, token
  budget) or a persistent model error (`ModelAPIError`): `budget` event +
  terminal commit, final status `budget`. **A normal main finish does not
  commit** (status `done` — the main run already wrote the deliverable);
  **a non-budget error ends the run without a commit** (status `error`).
  This is v3 parity — no "always commit at the end" behaviour.
- **The commit** (`prompts/v3commit.md`, byte-identical to the registered
  v3 `COMMIT_PROMPT`, test-locked) resumes the *trimmed* main history
  (no dangling tool calls; the task is re-stated if the history is
  empty), may spend up to `min(commit_time_cap, hard_time − elapsed)`
  (the soft check is disabled for the commit, the hard check stays
  active), skips with a log event below 10s, has its own request limit
  (25) and the `[phases.commit]` reasoning effort (sent as
  `reasoning_effort` only for the commit). It never fails the run.
- **Free text end to end**: the v3 main and commit have no typed output
  (`output_type = None`) — the deliverable is the file on disk, not
  structured phase output. The v5 `ReviewResult` commit is untouched.
- **Prompts**: `prompts/main.md` carries the adapted v3 SYSTEM_PROMPT
  sections (PROTOCOL / FORMAT DISCIPLINE / CODE FIX TASKS / BUDGET) with
  one line rendered from the `[v3loop]` values; the task instruction is
  the first user message (v3 parity).
- **Shared v5 machinery**: tools (30s bash cap, instrumented results,
  anti-injection wrapping), config layer, `TrackedModel` accounting,
  toolsets, state file, log event names. The v3 regime does not fork any
  of it.

## Verification

- 14 agent tests (`agent/tests/test_v3loop.py`): prompt provenance,
  done/budget/error paths, both breach kinds (usage limits + wall clock),
  commit skip below 10s, commit history resume + settings, arm mutation,
  v3loop/cycles runner dispatch.
- 11 CLI tests (`cli/tests/test_run_loop.py`): flag/env resolution,
  container + host-mode env pass-through, MLflow `loop` tag.
- Manual: `SLEPA_NO_DOCKER=1 shlepa run hello --loop v3` — the dispatch
  chain works end to end (v3loop `agent_start`, main phase, tool calls,
  error handling). Caveat: in host mode the task's `/app` paths do not
  exist on the host (pre-existing legacy-host-mode limitation, affects
  both regimes; the container mode is the contest-faithful default).

## Follow-ups (open)

- **A/B run**: v3 vs cycles on the benchmark preset (`shlepa run <preset>
  --loop v3` vs the default) with the same arm/model, then compare
  `solved`, `duration_sec` and per-phase tokens in MLflow. This is the
  point of the regime — until it lands, the budget defaults are the v3
  registered values, not measured optima.
- Tune `[v3loop]` from the A/B data (soft/hard split, token budget) once
  the task set's actual time limits are known per task.
- The v3 regime has no review/repair phase: a silently-broken
  deliverable is only caught by the task's own verifier. If the A/B shows
  regressions concentrated in format errors, consider a one-shot
  verification nudge inside the commit prompt rather than a new phase.
