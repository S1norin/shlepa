# Agent configuration (v4)

The agent reads all tuning values from a single file:

```
agent/shlepa_agent/config.toml
```

The file ships inside the package, so the submission zip carries it
automatically. Environment variables (`SHLEPA_*`) override individual keys
at runtime; **invalid env values are ignored** (the file value wins).

## Adaptive time budget

Each contest task has its own time limit **T** (seconds). The agent derives
a complete "budget world" from T at startup (`shlepa_agent/budget.py`):
phase caps, cycle count, commit window, bash cap, request/timeout caps.

**T extraction chain** (first hit wins, logged as `t_source`):

1. env — `SLEPA_AGENT_TIMEOUT` (set by the dev engine from `task.toml`),
   then `TASK_TIMEOUT_SEC` / `AGENT_TIMEOUT` / legacy names;
2. `task.toml` probe — `$TASK_DIR/task.toml`, then `/app/task.toml`,
   `/opt/harbor/local-agent/task.toml` (`[agent] timeout_sec`); a few
   milliseconds, harmless when the file is absent;
3. instruction text — e.g. "time limit: 90 seconds", "10 minutes";
4. fallback — `budget.t_fallback` (default 600s, override with
   `SHLEPA_BUDGET_T_FALLBACK`).

The token limit is resolved the same way (env → text → fallback 300k);
the tracked budget is 95% of it.

**Formulas** (T clamped to a minimum of 60s):

```
margin    = clamp(0.03·T, 5, 15)      hard = T − margin
reserve   = min(0.10·T, 90) if 0.10·T ≥ 20 else 0
                                      core = hard − reserve
plan      = 0        if core < 90
            30/45/60 by T (<200 / <300 / else), capped at core − 60
work      = min(180, core − plan − 30)   (≥30s, else the cycle is infeasible)
cycles    = max(1, floor((core − 30) / (plan + work)))
commit_cap= clamp(0.20·T, 45, 120)
bash_cap  = clamp(0.20·T, 10, 240)
finalize  = clamp(0.05·T, 5, 20)   (internal tail, not a phase)
```

No phase is ever given less than 30s — a phase that does not fit is cut
entirely (plan), and the finalize tail is cut below 20s. Every knob is
overridable via `[budget.form]` in `config.toml` (all defaults in
`budget.BudgetForm`); the shipped form section is empty (defaults).

Reference values for the default 600s task (also what the logs show when
no task limit is visible):

| T | plan | work | cycles | commit cap | bash cap | reserve |
|---:|---:|---:|---:|---:|---:|---:|
| 60 | — | 25 | 1 | 45 | 12 | 0 |
| 120 | 30 | 55 | 1 | 45 | 24 | 0 |
| 200 | 45 | 99 | 1 | 45 | 40 | 20 |
| 300 | 60 | 171 | 1 | 60 | 60 | 30 |
| 600 | 60 | 180 | 2 | 120 | 120 | 60 |
| 1200 | 60 | 180 | 4 | 120 | 240 | 90 |

Per-request caps shrink dynamically as time runs out:
`llm_timeout = min(180, time_left − margin)`,
`llm_wall = min(240, time_left − margin)`,
`bash_timeout = min(requested, bash_cap, time_left − margin − finalize)`.
A new LLM request is refused once `time_left < margin + 5` (GATE).

## The 4-phase pipeline

Every run walks a fixed phase graph. The entry is derived: `plan` when the
budget allocates plan time, otherwise straight to `work` (`agent.entry`
empty = derive; set it explicitly to force).

```
                 ┌──────────── replan (cycles < max_cycles) ───────────┐
                 ▼                                                      │
  plan ──> work ──> commit   (terminal, typed CommitResult)
    │        │
    │        └──> emergency   (only on deadline / step-guard breach,
    │                       or after work budget/budget-handoff)
    └── decision=commit ──> commit     (trivial-task shortcut)
```

| Phase      | Fresh/continued | Output       | Hard time cap | Request slice | Retries | Reasoning |
|------------|-----------------|--------------|---------------|---------------|---------|-----------|
| `plan`     | fresh run       | `PlanResult` (typed) | budget `plan` (30/45/60 by T) | 25 | 1 | — |
| `work`     | fresh run (gets the plan hand-off) | `WorkResult` (typed) | budget `work` (≤180s) | 100 | 1 | — |
| `commit`   | continues the work conversation | `CommitResult` (typed) | budget `commit_cap` (≤120s), ends on completion | 20 | 0 | low |
| `emergency`| continues the last conversation | free text (last-resort rescue) | `min(remaining)` (skipped below 10s) | 20 | 0 | low |

An explicit `[phases.*].time` overrides the budget-derived cap for that
phase (dev/testing knob); the shipped config leaves them unset.

Routing rules (runner):

- `plan` returns a typed `PlanResult` with `decision = work | commit`.
  `commit` is the trivial-task shortcut (the answer is already known).
- `work` returns a typed `WorkResult` with `decision = commit | replan`.
  `replan` re-enters `plan` while `state.cycles < max_cycles` **and** a
  full plan+work+commit cycle still fits in the remaining budget; after
  the cap (or when it no longer fits) the run is forced into `commit`
  (final status `budget`). `max_cycles` is derived from the budget
  (default 2 at T=600; `agent.max_cycles` > 0 overrides).
- `commit` returns a typed `CommitResult` (`status` ok/partial/unverified,
  `artifact`, `checks`, `notes`); the reported run output is
  `notes` (falling back to `artifact`).
- **Phase hard timeouts** (`plan`/`work` cap expiry) are budget
  hand-offs, not errors: the runner issues **one** toolless `final_ask`
  request on the same (trimmed) conversation — "time is up, write the
  deliverable now, no tools" — capped at `min(30s, remaining)`. The
  request prefix is byte-identical to the phase's last request so the
  local LLM server reuses its KV cache. After `final_ask`, `plan` hands
  off to `work` and `work` hands off to `commit`.
- **Commit deadline** (derived: `min(plan + work + commit_cap, hard −
  reserve)`; `agent.commit_deadline` > 0 overrides): at every phase
  boundary, if the run clock is past the deadline and the next phase is
  not already `commit`/`emergency`, the runner routes to `emergency`
  instead (it then runs until the remaining budget is spent). The
  deadline never fires while `commit` is running. A commit phase is also
  never started with less than 30s left (emergency instead).
- **Step guard** (derived from the budget; `agent.max_steps` > 0
  overrides): once the number of phase runs reaches the cap, the runner
  routes to `emergency` at the next boundary.
- `commit` and `emergency` are terminal: the run ends when they finish
  (or are skipped for lack of time).
- **Retries** apply to non-budget errors only: `plan` 1, `work` 1,
  `commit` 0, `emergency` 0. Budget results (time caps, request slices,
  token/usage limits) are never retried — they hand off per the rules
  above.
- **State hand-off**: after every phase the runner writes the run-state
  file (elapsed, cycles, budget, per-phase results) to
  `$SHLEPA_STATE_FILE` (default `/tmp/shlepa_state.json`) — never into the
  task workdir.

## Env-var overrides

| Env var | Config key | Type |
|---|---|---|
| `SHLEPA_TEMP` | `agent.temp` | float (sent only when `send_temp` is on) |
| `SHLEPA_SEND_TEMP` | `agent.send_temp` | 1/0 (bool) |
| `SHLEPA_MAX_STEPS` | `agent.max_steps` | int (0 = derive) |
| `SHLEPA_MAX_CYCLES` | `agent.max_cycles` | int (0 = derive) |
| `SHLEPA_STATE_FILE` | — | run-state file path (default `/tmp/shlepa_state.json`, never the workdir) |
| `SHLEPA_COMMIT_DEADLINE` | `agent.commit_deadline` | float (0 = derive) |
| `SHLEPA_BUDGET_HARD_TIME` | `budget.hard_time` | float (reference) |
| `SHLEPA_BUDGET_T_FALLBACK` | `budget.t_fallback` | float |
| `SHLEPA_BUDGET_SOFT_TIME` | `budget.soft_time` | float |
| `SHLEPA_BUDGET_REQUEST_LIMIT` | `budget.request_limit` | int |
| `SHLEPA_BUDGET_TOKEN_BUDGET` | `budget.token_budget` | int |
| `SHLEPA_BUDGET_MAX_TOKENS` | `budget.max_tokens` | int |
| `SHLEPA_BUDGET_REQUEST_TIMEOUT` | `budget.request_timeout` | float |
| `SHLEPA_BUDGET_REQUEST_WALL` | `budget.request_wall` | float |
| `SHLEPA_BASH_TIMEOUT` | `tools.bash.timeout` (default per-call timeout) | float |
| `SHLEPA_BASH_MAX_TIMEOUT` | `tools.bash.max_timeout` (hard cap) | float |
| `SHLEPA_BASH_MAX_OUTPUT` | `tools.bash.max_output` | int |
| `SHLEPA_READ_MAX_LIMIT` | `tools.read.max_limit` | int |
| `SHLEPA_READ_MAX_OUTPUT` | `tools.read.max_output` | int |
| `SHLEPA_COMMIT_TIME` | `phases.commit.time` (default: remainder) | float |
| `SHLEPA_COMMIT_REQUEST_LIMIT` | `phases.commit.requests` | int |
| `SHLEPA_COMMIT_REASONING_EFFORT` | `phases.commit.reasoning_effort` | str |

Model/endpoint variables are unchanged (set by the harness, not the
config): `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

## Budgets: hard vs advisory

- **Hard, enforced by `TrackedModel`** (all derived from T at startup):
  `hard = T − margin` (wall-clock backstop; 585s at T=600),
  `budget.request_limit` (90 requests, anti-loop guard),
  `token_budget` (95% of the task token limit, 285k at the fallback),
  `budget.max_tokens` (per-request output cap), dynamic per-request
  timeout/wall (see formulas above) and the request GATE.
- **Hard, enforced by the runner**: per-phase time caps (budget-derived
  `plan`/`work`, `commit_cap`; `[phases.*].time` overrides), per-phase
  request slices (`phases.*.requests`), the derived commit deadline and
  step guard, the derived cycle cap.
- **Advisory (rendered into prompts/status, never enforced)**:
  `budget.soft_time` (reference for T=600) and per-phase
  `soft_time`/`soft_tokens` (`plan`: 45s/15k, `work`: 150s/80k,
  `commit`/`emergency`: 45s/20k).

## Sections overview

- `[agent]` — pipeline entry, emergency phase, cycle cap, commit
  deadline, step guard, temperature (opt-in: sent to the endpoint only
  when `send_temp` is enabled; default: not sent, the endpoint decides).
- `[budget]` — global wall-clock/token/request budgets (TrackedModel).
- `[tools.*]` — per-tool `enabled` plus caps: `timeout`/`max_timeout`/
  `max_output` (bash), `max_limit`/`max_output`/`max_file_mb` (read),
  `max_file_mb` (edit). File tools (read/write/edit) have a hard 5s
  per-call timeout; read/edit reject files larger than `max_file_mb`
  (default 100 MB) with a bash hint instead of loading them.
- `[phases.*]` — per-phase toolset, request/time slices, advisory soft
  limits, reasoning effort, retry count, template wrapper overrides.
- `[template]` — ordered block list + per-block wrappers for the common
  request template (the `previous_results`, `output_schema` and `note`
  blocks are reserved for the pipeline hand-offs and structured output
  schemas).

## Log events

The agent logs one JSON line per event on stdout (marker
`SLEPA_AGENT_METRICS_JSON=`). CLI-parsed events keep their names and
fields:

| Event | Fields | Notes |
|---|---|---|
| `agent_start` | `model`, `base_url`, `workdir`, `prompt`, `temp`, `soft_time`, `hard_time`, `request_limit`, `token_budget` | first line of a run (the four stable CLI fields stay; `soft_time`/`hard_time` are now the derived values). `temp` is present only when `agent.send_temp` is enabled. Additive: `entry`, `emergency`, `max_cycles`, `commit_deadline`, `max_steps`, `t`, `t_source`, `plan_cap`, `work_cap`, `reserve`, `bash_cap` (CLI ignores unknown fields) |
| `usage` | `request`, `input_tokens`, `output_tokens`, `cumulative_input`, `cumulative_output`, `cumulative_total`, `elapsed_s` | per model request |
| `agent_done` | `status`, `elapsed_s`, `output` | final line; `status` ∈ `done` / `budget` / `error` |
| `agent_error` | `error`, `elapsed_s` | unexpected failure (the run still exits 0) |

Additive pipeline events (v3):

| Event | Fields | Notes |
|---|---|---|
| `phase` | `id`, `start`/`skipped`, `cycle`, `requests`, `cap_s`, `elapsed_s` | phase entry (and skip with reason) |
| `phase_done` | `id`, `status`, `duration_s`, `elapsed_s` | phase exit |
| `phase_retry` | `phase`, `attempt`, `elapsed_s` | non-budget error retry |
| `final_ask` | `phase`, `start`/`ok`, `cap_s`, `history_messages`, `elapsed_s` | one-shot toolless rescue request |
| `deadline` | `elapsed_s` | commit deadline routed the run to emergency |
| `budget` | `reason`, `elapsed_s` (+ `detail` when reason=`derived`) | budget hand-off (time cap, request slice, max_cycles, max_steps, …); `derived` logs the whole budget world at startup |
| `commit` | `phase`, `start`/`skipped`, `history_messages`, `time_cap_s`, `elapsed_s` | commit/emergency terminal entry |
| `llm_thinking` / `llm_tool_call` / `llm_tool_result` / `run_usage` | (v2, unchanged) | per-request observability |

## Instrumented tool results

Every tool result sent to the model is wrapped by `format_tool_result`
(`shlepa_agent/tools/base.py`) in a fixed layout:

```
[tool] name(arg1=..., arg2=...)
  spent=0.31s ended_at=42.7s time_left=542.3s
  NOTE: timeout clamped to 120s (max)      <- optional, e.g. clamped params
  FAILED: command killed after 120s timeout (exit 124)   <- optional, failure only
UNTRUSTED TEXT ---------------               <- read/bash only
<tool output or error>
END OF UNTRUSTED TEXT-----------
```

- `spent` — tool wall time; `ended_at` — seconds into the run (the same
  clock as the global budget); `time_left` — until `budget.hard_time`.
- `FAILED:` is emitted only on tool failure (e.g. file not found, edit
  validation error, bash spawn error / timeout kill). Non-zero bash exit
  codes stay plain output — the model sees `[exit_code]` in the body.
- The `UNTRUSTED TEXT` block marks environment data (file content,
  command output) as data, not instructions (anti-prompt-injection).
  `write`/`edit` return status lines without the block.
- Long argument values in the header are truncated to 200 chars.
