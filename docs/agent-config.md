# Agent configuration (v5/v6)

The agent reads all tuning values from a single file:

```
agent/shlepa_agent/config.toml
```

The file ships inside the package, so the submission zip carries it
automatically. Environment variables (`SHLEPA_*`) override individual keys
at runtime; **invalid env values are ignored** (the file value wins).

## Fixed cycle regime (v5)

There is **NO task time limit T** in the agent — not detected, not
assumed, not logged (issue #63: the contest does not expose T to the
agent anyway). The agent works in plan → work → review **cycles** and the
only bounds are the fixed per-operation constants
(`shlepa_agent/budget.py`):

```
plan   = 30s    work = 120s per cycle    review (commit) = 45s
bash   = 30s per call (also the tool max)
llm wall = 180s per request (open -> last chunk)
full cycle = plan + work + review = 195s
```

(v6: the plan cap dropped from 60s to 30s and is env-overridable via
`SHLEPA_PLAN_TIME`; an explicit `[phases.plan].time` overrides it for
single runs.)

There is **NO global hard stop, NO request-start gate and NO cycle cap**:
the run stops only when (a) the review verdict is `done`, (b) a phase
fails after its retries (status `error`), or (c) the container itself is
killed at the task's own limit (the external boundary — the work phase
keeps the deliverable file fresh on disk, so the partial result is what
scores). There is also **NO token budget and NO request-count limit**
(issue #62): token usage is still logged per request (telemetry /
tie-break analysis) but never enforced.

## The plan → work → review cycle (v5)

Every run walks the phase graph (phase ids: `plan`, `work`, `commit` — the
commit phase is the **reviewer**). The entry is always `plan` (`agent.entry`
is a dev knob to force `work`).

```
   ┌────────────────── next_round (always) ──────────────────┐
   ▼                                                        │
plan ──> work ──> review (commit)   (terminal, typed ReviewResult)
```

(v6: the pipeline is strictly linear — the old `decision=commit`
trivial-task shortcut is gone, every plan flows to WORK. A plan cut by
its cap gets one toolless `final_ask` (typed partial hand-off +
deterministic LAST_TOOLS tail) and then enters WORK, not the review.)

| Phase      | Fresh/continued | Output         | Hard time cap | Retries | Reasoning |
|------------|-----------------|----------------|---------------|---------|-----------|
| `plan`     | fresh run       | `PlanResult` (typed) | 30s (`SHLEPA_PLAN_TIME`) | 1 | — |
| `work`     | fresh run (gets the plan hand-off) | `WorkResult` (typed) | 120s per cycle | 1 | — |
| `commit`   | continues the work conversation | `ReviewResult` (typed) | 45s; the terminal handler | 0 | low |
| `emergency`| — (UNUSED in v5, kept in code) | — | — | 0 | low |

v6 toolsets: `plan` is read-only (`read`, `recon`, `search` — no
bash/write/edit); `work` gained `recon` and `search` on top of
`read/write/edit/bash`; `commit` is unchanged.

An explicit `[phases.*].time` overrides the regime cap for that phase
(dev/testing knob); the shipped config leaves them unset.

Routing rules (runner, v6):

- The pipeline is strictly linear: a done `plan` (typed `PlanResult`,
  `goal`/`findings`/`steps`/`risks` — no routing field) **always** flows
  to WORK, even a trivial plan. WORK always flows to the review.
- `plan` timeout → one toolless `final_ask` on the plan conversation, then
  WORK. With the v6 default (`SHLEPA_HANDOFF=partial`) the final_ask is
  typed: the model emits a `PartialHandoff` (objective, findings,
  files_seen, hypotheses, failed_paths, next_action,
  deliverable_path_if_known) and the harness independently extracts the
  deterministic LAST_TOOLS tail (last 6 tool calls with capped args and
  results, `SHLEPA_LAST_TOOLS_N`). Both land in the fresh WORK prompt —
  the full plan transcript is never carried (KV-cache: the final_ask
  prefix is byte-identical to the plan's last request).
- `plan` error (after retries) → WORK with a direct-execution note
  (there is no plan to follow).
- `work` returns a typed `WorkResult` (`summary`, `findings`,
  `deliverable`, `confidence`).
- `review` (the commit phase) returns a typed `ReviewResult`
  (`status` ok/partial, `verdict` done/next_round, `artifact`, `checks`,
  `hints`, `notes`); the reported run output is `notes` (falling back to
  `artifact`). The reviewer has full tools and verifies the deliverable
  mechanically, repairing it if broken.
- **Cycle continuation**: a `verdict = next_round` **always** starts a new
  plan/work cycle (logged as a `cycle` event). There is no cycle cap and
  no time check — the container kill at the task's own limit is the only
  external bound.
- **Phase hard timeouts** (`plan`/`work` cap expiry) and phase errors are
  hand-offs, not crashes. Work timeout: one toolless `final_ask` on the
  same conversation — "time is up, write the deliverable now, no tools" —
  capped at 30s, then the review phase. Plan timeout: one `final_ask`
  (typed partial hand-off under the v6 default) then WORK. Both requests
  reuse the phase's last request prefix byte-for-byte (KV-cache reuse on
  the local LLM server). The `final_ask` log event carries the `mode`
  (`off` = v5 message, `partial` = typed hand-off).
- **The emergency phase** (v4 terminal rescue) is UNUSED: routing to it is
  hard-off, the class and config section are kept for compatibility.
- **Step guard** (`agent.max_steps` > 0, dev knob, off by default): once
  the number of phase runs reaches the cap, the run stops at the next
  boundary (final status `timeout`).
- The review phase is terminal: the run ends when it finishes.
- **Retries** apply to non-timeout errors only: `plan` 1, `work` 1,
  `commit` 0. Timeout results (time caps, context-limit breaches) are
  never retried — they hand off per the rules above.
- **State hand-off**: after every phase the runner persists the run state
  (elapsed, cycles, regime, per-phase results) to the run-state file
  (`$SHLEPA_STATE_FILE`, default `/tmp/shlepa_state.json`) — never into
  the task workdir; the structured bridge between phases and cycles.

## Env-var overrides

| Env var | Config key | Type |
|---|---|---|
| `SHLEPA_TEMP` | `agent.temp` | float (sent only when `send_temp` is on) |
| `SHLEPA_SEND_TEMP` | `agent.send_temp` | 1/0 (bool) |
| `SHLEPA_MAX_STEPS` | `agent.max_steps` | int (0 = off, the run cycles until done) |
| `SHLEPA_STATE_FILE` | — | run-state file path (default `/tmp/shlepa_state.json`, never the workdir) |
| `SHLEPA_BUDGET_MAX_TOKENS` | `budget.max_tokens` | int |
| `SHLEPA_BUDGET_REQUEST_TIMEOUT` | `budget.request_timeout` | float |
| `SHLEPA_BASH_TIMEOUT` | `tools.bash.timeout` (default per-call timeout) | float |
| `SHLEPA_BASH_MAX_TIMEOUT` | `tools.bash.max_timeout` (hard cap) | float |
| `SHLEPA_BASH_MAX_OUTPUT` | `tools.bash.max_output` | int |
| `SHLEPA_READ_MAX_LIMIT` | `tools.read.max_limit` | int |
| `SHLEPA_READ_MAX_OUTPUT` | `tools.read.max_output` | int |
| `SHLEPA_COMMIT_TIME` | `phases.commit.time` (default: review cap 45s) | float |
| `SHLEPA_COMMIT_REASONING_EFFORT` | `phases.commit.reasoning_effort` | str |
| `SHLEPA_PLAN_TIME` | `phases.plan.time` (default: plan cap 30s) | float |
| `SHLEPA_SEARCH` | `tools.search.enabled` | 1/0 (bool; 0 disables the search tool) |
| `SHLEPA_ROUTE_PLAN_TIMEOUT` | `agent.route_plan_failure` | str: `work` (v6 default) \| `commit` (v5 routing, A0 arm) |
| `SHLEPA_HANDOFF` | `agent.handoff` | str: `partial` (v6 default) \| `off` (v5 final_ask message, A1 arm) |
| `SHLEPA_LAST_TOOLS_N` | — (read directly by the harness) | int: how many last tool calls go into the LAST_TOOLS block (default 6, 0 disables) |

The A/B arms for the v6 rollout: `SHLEPA_ROUTE_PLAN_TIMEOUT=commit` +
`SHLEPA_HANDOFF=off` reproduce the v5 routes exactly (A0);
`SHLEPA_ROUTE_PLAN_TIMEOUT=work` + `SHLEPA_HANDOFF=off` isolates the
routing change (A1); the defaults are the full v6 (A2).

Model/endpoint variables are unchanged (set by the harness, not the
config): `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

## Bounds: hard vs advisory

- **Hard, enforced by `TrackedModel`** (per request, no horizon):
  the open timeout `request_timeout = 180s` and the wall cap
  `llm_wall = 180s` (open -> last chunk). There is NO hard stop, NO
  request-start gate, NO request-count limit and NO token budget.
- **Hard, enforced by the runner**: the fixed per-phase time caps (plan
  30s / work 120s / review 45s; `[phases.*].time` overrides) and the
  optional step guard.
- **Hard, enforced by the environment**: the container kill at the
  task's own time limit — the only external bound on the cycles.
- **Advisory (rendered into prompts/status, never enforced)**:
  per-phase `soft_time`/`soft_tokens` (`plan`: 25s/15k, `work`: 105s — no
  token note for work, `commit`: 35s/20k; every soft time stays under its
  phase's hard cap) and `phases.*.requests` (legacy slices, no longer
  enforced — kept as prompt context only).

## Sections overview

- `[agent]` — pipeline entry (dev knob, default `plan`), temperature
  (opt-in: sent to the endpoint only when `send_temp` is enabled; default:
  not sent, the endpoint decides), step guard (dev knob), emergency
  phase name (unused in v5).
- `[budget]` — per-request caps: `max_tokens`, `request_timeout`
  (the phase caps are constants in `budget.py`).
- `[tools.*]` — per-tool `enabled` plus caps: `timeout`/`max_timeout`/
  `max_output` (bash), `max_limit`/`max_output`/`max_file_mb` (read),
  `max_file_mb` (edit). File tools (read/write/edit) have a hard 5s
  per-call timeout; read/edit reject files larger than `max_file_mb`
  (default 100 MB) with a bash hint instead of loading them. Bash runs
  each command in its own session (process group): the per-call timeout
  (default 30s, hard cap 30s) SIGKILLs the whole group — backgrounded
  children included — and stdout/stderr are drained with bounded
  head+tail retention (middle replaced by a
  `[...N bytes dropped...]` marker), so an unbounded `yes`/`dd` cannot
  blow up memory or the result.
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
| `agent_start` | `model`, `base_url`, `workdir`, `prompt`, `entry` | first line of a run (the stable CLI fields stay; `temp` is present only when `agent.send_temp` is enabled). Additive (v5): `emergency`, `max_steps`, `plan_cap`, `work_cap`, `review_cap`, `bash_cap`, `llm_wall` (CLI ignores unknown fields; there is NO `t`/`t_source`/`hard_time`/`soft_time`/`commit_deadline`) |
| `usage` | `request`, `input_tokens`, `output_tokens`, `cache_read`, `cache_write`, `cumulative_input`, `cumulative_output`, `cumulative_cache_read`, `cumulative_cache_write`, `cumulative_total`, `elapsed_s` | per model request (v6: prompt-cache counters, 0 when the endpoint reports none) |
| `agent_done` | `status`, `elapsed_s`, `output` | final line; `status` ∈ `done` / `timeout` / `error` |
| `agent_error` | `error`, `elapsed_s` | unexpected failure (the run still exits 0) |

Additive pipeline events (v3):

| Event | Fields | Notes |
|---|---|---|
| `phase` | `id`, `start`, `cycle`, `requests`, `cap_s`, `elapsed_s` | phase entry (no more skips — there is no horizon to run out of) |
| `phase_done` | `id`, `status`, `duration_s`, `elapsed_s` | phase exit |
| `phase_retry` | `phase`, `attempt`, `elapsed_s` | non-budget error retry |
| `final_ask` | `phase`, `mode`, `start`/`ok`, `cap_s`, `history_messages`, `elapsed_s` | one-shot toolless rescue request (`mode`: `off` = v5 message, `partial` = typed hand-off) |
| `cycle` | `reason`, `cycle`, `elapsed_s` | a `next_round` review verdict started a new plan/work cycle (always) |
| `budget` | `reason`, `elapsed_s` (+ `detail`) | regime hand-off (`regime` logs the fixed caps at startup; `<phase> time cap`, `max_steps`, …) |
| `commit` | `phase`, `start`, `history_messages`, `time_cap_s`, `elapsed_s` | review (commit) terminal entry |
| `llm_thinking` / `llm_tool_call` / `llm_tool_result` / `run_usage` | (v2, unchanged) | per-request observability |

## Instrumented tool results

Every tool result sent to the model is wrapped by `format_tool_result`
(`shlepa_agent/tools/base.py`) in a fixed layout:

```
[tool] name(arg1=..., arg2=...)
  spent=0.31s ended_at=42.7s
  NOTE: timeout clamped to 30s (max)       <- optional, e.g. clamped params
  FAILED: command killed after 30s timeout (exit 124)    <- optional, failure only
UNTRUSTED TEXT ---------------               <- read/bash only
<tool output or error>
END OF UNTRUSTED TEXT-----------
```

- `spent` — tool wall time; `ended_at` — seconds into the run. There is no
  `time_left` field: v5 has no global hard deadline.
- `FAILED:` is emitted only on tool failure (e.g. file not found, edit
  validation error, bash spawn error / timeout kill). Non-zero bash exit
  codes stay plain output — the model sees `[exit_code]` in the body.
- The `UNTRUSTED TEXT` block marks environment data (file content,
  command output) as data, not instructions (anti-prompt-injection).
  `write`/`edit` return status lines without the block.
- Long argument values in the header are truncated to 200 chars.
