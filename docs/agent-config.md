# Agent configuration (v5)

The agent reads all tuning values from a single file:

```
agent/shlepa_agent/config.toml
```

The file ships inside the package, so the submission zip carries it
automatically. Environment variables (`SHLEPA_*`) override individual keys
at runtime; **invalid env values are ignored** (the file value wins).

## Fixed time regime (v5)

All phase caps are **fixed constants** (`shlepa_agent/budget.py`); the only
per-task value is the task time limit **T** (the "horizon"), which sets the
hard stop and clamps the caps at phase start:

```
plan   = 60s    work = 120s per cycle    review (commit) = 45s
margin = 15s → hard stop = T − 15s
bash   = 30s per call (also the tool max)
llm wall = 180s per request (clamped to the remaining time)
gate   = 20s — no new LLM request when time_left < 20s
full cycle = plan + work + review = 225s
```

T is the ONLY derived number (issue #63: the contest does not guarantee T
in the instruction or the environment, so the agent must work with a
fallback): the **T detection chain** (first hit wins, logged as
`t_source`):

1. env — `SLEPA_AGENT_TIMEOUT` (set by the dev engine from `task.toml`),
   then `TASK_TIMEOUT_SEC` / `TASK_TIME_LIMIT_SEC` / `AGENT_TIMEOUT_SEC` /
   `TIME_LIMIT_SEC` / `TASK_LIMIT_SEC`;
2. `task.toml` probe — `$TASK_DIR/task.toml`, then `/app/task.toml`,
   `/opt/harbor/local-agent/task.toml` (`[agent] timeout_sec`); a few
   milliseconds, harmless when the file is absent;
3. instruction text — e.g. "time limit: 90 seconds", "10 minutes";
4. fallback — `budget.t_fallback` (default 600s, override with
   `SHLEPA_BUDGET_T_FALLBACK`).

T is clamped to a minimum of 60s and is used for the horizon only (hard
stop + entry phase); phase caps are never scaled from it. There is **NO
token budget and NO request-count limit** (issue #62): token usage is still
logged per request (telemetry / tie-break analysis) but never enforced.
`[budget.form]` and the adaptive formulas are removed.

## The plan → work → review cycle (v5)

Every run walks the phase graph (phase ids: `plan`, `work`, `commit` — the
commit phase is the **reviewer**). The entry is derived: `plan` when a full
cycle (225s) fits before the hard stop, otherwise straight to `work`
(`agent.entry` empty = derive; set it explicitly to force).

```
   ┌────────────── next_round (a full cycle still fits) ──────────────┐
   ▼                                                                  │
plan ──> work ──> review (commit)   (terminal, typed ReviewResult)
   │
   └── decision=commit ──> review     (trivial-task shortcut)
```

| Phase      | Fresh/continued | Output         | Hard time cap | Retries | Reasoning |
|------------|-----------------|----------------|---------------|---------|-----------|
| `plan`     | fresh run       | `PlanResult` (typed) | 60s (clamped to the time left) | 1 | — |
| `work`     | fresh run (gets the plan hand-off) | `WorkResult` (typed) | 120s per cycle (clamped) | 1 | — |
| `commit`   | continues the work conversation | `ReviewResult` (typed) | 45s (clamped); the terminal handler | 0 | low |
| `emergency`| — (UNUSED in v5, kept in code) | — | — | 0 | low |

An explicit `[phases.*].time` overrides the budget-derived cap for that
phase (dev/testing knob); the shipped config leaves them unset.

Routing rules (runner):

- `plan` returns a typed `PlanResult` with `decision = work | commit`.
  `commit` is the trivial-task shortcut (the answer is already known); the
  review phase then verifies it.
- `work` returns a typed `WorkResult` (`summary`, `findings`,
  `deliverable`, `confidence`) — it has **no decision**: the run always
  continues to the review phase.
- `review` (the commit phase) returns a typed `ReviewResult`
  (`status` ok/partial, `verdict` done/next_round, `artifact`, `checks`,
  `hints`, `notes`); the reported run output is `notes` (falling back to
  `artifact`). The reviewer has full tools and verifies the deliverable
  mechanically, repairing it if broken.
- **Cycle continuation**: a `verdict = next_round` starts a new
  plan/work cycle **only when a full cycle (225s) still fits** before the
  hard stop. There is **no cycle cap** — rounds are time-driven. A
  `next_round` verdict without a fitting cycle stops the run (final status
  `budget`).
- **Phase hard timeouts** (`plan`/`work` cap expiry) and phase errors are
  hand-offs, not crashes: on a timeout the runner issues **one** toolless
  `final_ask` request on the same conversation — "time is up, write the
  deliverable now, no tools" — capped at `min(30s, remaining)`, then hands
  off to the review phase (the request prefix is byte-identical to the
  phase's last request, so the local LLM server reuses its KV cache).
- **Review window**: the review phase is never started with less than 30s
  left — the run stops with whatever exists on disk.
- **Commit deadline**: the derived `commit_deadline`
  (`min(full cycle, hard)`; `agent.commit_deadline` > 0 overrides) is
  **logged only** (stable `agent_start` field for the CLI) — in v5 it
  routes nothing. The `emergency` phase (v4 terminal rescue) is UNUSED:
  routing to it is hard-off, the class and config section are kept for
  compatibility.
- **Step guard** (`agent.max_steps` > 0, dev knob, off by default): once
  the number of phase runs reaches the cap, the run stops at the next
  boundary (final status `budget`).
- The review phase is terminal: the run ends when it finishes (or is
  skipped for lack of time).
- **Retries** apply to non-budget errors only: `plan` 1, `work` 1,
  `commit` 0. Budget results (time caps) are never retried — they hand
  off per the rules above.
- **State hand-off**: after every phase the runner persists the run state
  (elapsed, cycles, budget, per-phase results) to the state file — the
  structured bridge between phases and cycles.

## Env-var overrides

| Env var | Config key | Type |
|---|---|---|
| `SHLEPA_TEMP` | `agent.temp` | float |
| `SHLEPA_MAX_STEPS` | `agent.max_steps` | int (0 = off, time is the bound) |
| `SHLEPA_COMMIT_DEADLINE` | `agent.commit_deadline` | float (0 = derive; logged only, routes nothing) |
| `SHLEPA_BUDGET_HARD_TIME` | `budget.hard_time` | float (legacy reference) |
| `SHLEPA_BUDGET_T_FALLBACK` | `budget.t_fallback` | float |
| `SHLEPA_BUDGET_SOFT_TIME` | `budget.soft_time` | float (legacy reference) |
| `SHLEPA_BUDGET_MAX_TOKENS` | `budget.max_tokens` | int |
| `SHLEPA_BUDGET_REQUEST_TIMEOUT` | `budget.request_timeout` | float |
| `SHLEPA_BUDGET_REQUEST_WALL` | `budget.request_wall` | float |
| `SHLEPA_BASH_TIMEOUT` | `tools.bash.timeout` (default per-call timeout) | float |
| `SHLEPA_BASH_MAX_TIMEOUT` | `tools.bash.max_timeout` (hard cap) | float |
| `SHLEPA_BASH_MAX_OUTPUT` | `tools.bash.max_output` | int |
| `SHLEPA_READ_MAX_LIMIT` | `tools.read.max_limit` | int |
| `SHLEPA_READ_MAX_OUTPUT` | `tools.read.max_output` | int |
| `SHLEPA_COMMIT_TIME` | `phases.commit.time` (default: review cap 45s) | float |
| `SHLEPA_COMMIT_REASONING_EFFORT` | `phases.commit.reasoning_effort` | str |

Model/endpoint variables are unchanged (set by the harness, not the
config): `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

## Budgets: hard vs advisory

- **Hard, enforced by `TrackedModel`** (from the fixed regime + T):
  `hard = T − 15s` (wall-clock backstop; 585s at T=600), the per-request
  wall cap `llm_wall = 180s` clamped to the remaining time, and the
  request GATE (no new LLM request when `time_left < 20s`). There is NO
  request-count limit and NO token budget.
- **Hard, enforced by the runner**: the fixed per-phase time caps (plan
  60s / work 120s / review 45s, clamped to the time left; `[phases.*].time`
  overrides) and the optional step guard.
- **Advisory (rendered into prompts/status, never enforced)**:
  per-phase `soft_time`/`soft_tokens` (`plan`: 45s/15k, `work`: 150s/80k,
  `commit`: 45s/20k) and `phases.*.requests` (legacy slices, no longer
  enforced — kept as prompt context only).

## Sections overview

- `[agent]` — pipeline entry, temperature, commit deadline (logged
  only), step guard (dev knob), emergency phase name (unused in v5).
- `[budget]` — T fallback + legacy reference values (`hard_time` /
  `soft_time`), `max_tokens`, request timeout/wall.
- `[tools.*]` — per-tool `enabled` plus caps: `timeout`/`max_timeout`/
  `max_output` (bash), `max_limit`/`max_output` (read).
- `[phases.*]` — per-phase toolset, advisory soft limits, reasoning
  effort, retry count, template wrapper overrides.
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
| `agent_start` | `model`, `base_url`, `workdir`, `prompt`, `temp`, `soft_time`, `hard_time` | first line of a run (the four stable CLI fields stay; `soft_time`/`hard_time` are the derived values). Additive (v5): `entry`, `emergency`, `commit_deadline`, `max_steps`, `t`, `t_source`, `plan_cap`, `work_cap`, `review_cap`, `bash_cap`, `llm_wall` (CLI ignores unknown fields) |
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
| `deadline` | `phase`, `reason`, `time_left_s`, `elapsed_s` | the review phase was not worth starting (<30s left) — the run stopped with what exists |
| `cycle` | `reason`, `cycle`, `elapsed_s` | a `next_round` review verdict started a new plan/work cycle |
| `budget` | `reason`, `elapsed_s` (+ `detail`) | budget hand-off (`derived` logs the regime at startup; `<phase> time cap`, `next_round_no_time`, `max_steps`, …) |
| `commit` | `phase`, `start`, `history_messages`, `time_cap_s`, `elapsed_s` | review (commit) terminal entry |
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
