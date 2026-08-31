# Agent configuration (v5)

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
plan   = 60s    work = 120s per cycle    review (commit) = 45s
bash   = 30s per call (also the tool max)
llm wall = 180s per request (open -> last chunk)
full cycle = plan + work + review = 225s
```

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
   │
   └── decision=commit ──> review     (trivial-task shortcut)
```

| Phase      | Fresh/continued | Output         | Hard time cap | Retries | Reasoning |
|------------|-----------------|----------------|---------------|---------|-----------|
| `plan`     | fresh run       | `PlanResult` (typed) | 60s | 1 | — |
| `work`     | fresh run (gets the plan hand-off) | `WorkResult` (typed) | 120s per cycle | 1 | — |
| `commit`   | continues the work conversation | `ReviewResult` (typed) | 45s; the terminal handler | 0 | low |
| `emergency`| — (UNUSED in v5, kept in code) | — | — | 0 | low |

An explicit `[phases.*].time` overrides the regime cap for that phase
(dev/testing knob); the shipped config leaves them unset.

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
- **Cycle continuation**: a `verdict = next_round` **always** starts a new
  plan/work cycle (logged as a `cycle` event). There is no cycle cap and
  no time check — the container kill at the task's own limit is the only
  external bound.
- **Phase hard timeouts** (`plan`/`work` cap expiry) and phase errors are
  hand-offs, not crashes: on a timeout the runner issues **one** toolless
  `final_ask` request on the same conversation — "time is up, write the
  deliverable now, no tools" — capped at 30s, then hands off to the
  review phase (the request prefix is byte-identical to the phase's last
  request, so the local LLM server reuses its KV cache).
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
  (elapsed, cycles, regime, per-phase results) to the state file — the
  structured bridge between phases and cycles.

## Env-var overrides

| Env var | Config key | Type |
|---|---|---|
| `SHLEPA_TEMP` | `agent.temp` | float |
| `SHLEPA_MAX_STEPS` | `agent.max_steps` | int (0 = off, the run cycles until done) |
| `SHLEPA_BUDGET_MAX_TOKENS` | `budget.max_tokens` | int |
| `SHLEPA_BUDGET_REQUEST_TIMEOUT` | `budget.request_timeout` | float |
| `SHLEPA_BASH_TIMEOUT` | `tools.bash.timeout` (default per-call timeout) | float |
| `SHLEPA_BASH_MAX_TIMEOUT` | `tools.bash.max_timeout` (hard cap) | float |
| `SHLEPA_BASH_MAX_OUTPUT` | `tools.bash.max_output` | int |
| `SHLEPA_READ_MAX_LIMIT` | `tools.read.max_limit` | int |
| `SHLEPA_READ_MAX_OUTPUT` | `tools.read.max_output` | int |
| `SHLEPA_COMMIT_TIME` | `phases.commit.time` (default: review cap 45s) | float |
| `SHLEPA_COMMIT_REASONING_EFFORT` | `phases.commit.reasoning_effort` | str |

Model/endpoint variables are unchanged (set by the harness, not the
config): `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

## Bounds: hard vs advisory

- **Hard, enforced by `TrackedModel`** (per request, no horizon):
  the open timeout `request_timeout = 180s` and the wall cap
  `llm_wall = 180s` (open -> last chunk). There is NO hard stop, NO
  request-start gate, NO request-count limit and NO token budget.
- **Hard, enforced by the runner**: the fixed per-phase time caps (plan
  60s / work 120s / review 45s; `[phases.*].time` overrides) and the
  optional step guard.
- **Hard, enforced by the environment**: the container kill at the
  task's own time limit — the only external bound on the cycles.
- **Advisory (rendered into prompts/status, never enforced)**:
  per-phase `soft_time`/`soft_tokens` (`plan`: 45s/15k, `work`: 150s/80k,
  `commit`: 45s/20k) and `phases.*.requests` (legacy slices, no longer
  enforced — kept as prompt context only).

## Sections overview

- `[agent]` — pipeline entry (dev knob, default `plan`), temperature,
  step guard (dev knob), emergency phase name (unused in v5).
- `[budget]` — per-request caps: `max_tokens`, `request_timeout`
  (the phase caps are constants in `budget.py`).
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
| `agent_start` | `model`, `base_url`, `workdir`, `prompt`, `temp`, `entry` | first line of a run (the stable CLI fields stay). Additive (v5): `emergency`, `max_steps`, `plan_cap`, `work_cap`, `review_cap`, `bash_cap`, `llm_wall` (CLI ignores unknown fields; there is NO `t`/`t_source`/`hard_time`/`soft_time`/`commit_deadline`) |
| `usage` | `request`, `input_tokens`, `output_tokens`, `cumulative_input`, `cumulative_output`, `cumulative_total`, `elapsed_s` | per model request |
| `agent_done` | `status`, `elapsed_s`, `output` | final line; `status` ∈ `done` / `timeout` / `error` |
| `agent_error` | `error`, `elapsed_s` | unexpected failure (the run still exits 0) |

Additive pipeline events (v3):

| Event | Fields | Notes |
|---|---|---|
| `phase` | `id`, `start`, `cycle`, `requests`, `cap_s`, `elapsed_s` | phase entry (no more skips — there is no horizon to run out of) |
| `phase_done` | `id`, `status`, `duration_s`, `elapsed_s` | phase exit |
| `phase_retry` | `phase`, `attempt`, `elapsed_s` | non-budget error retry |
| `final_ask` | `phase`, `start`/`ok`, `cap_s`, `history_messages`, `elapsed_s` | one-shot toolless rescue request |
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
