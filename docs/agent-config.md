# Agent configuration (v6-rewrite)

The agent reads all tuning values from a single file:

```
agent/shlepa_agent/config.toml
```

The file ships inside the package, so the submission zip carries it
automatically. Environment variables (`SHLEPA_*`) override individual keys
at runtime; **invalid env values are ignored** (the file value wins).

## Fixed regime (v6-rewrite)

There is **NO task time limit T** in the agent — not detected, not
assumed, not logged (issue #63: the contest does not expose T to the
agent anyway). The agent runs a **hard number of plan → work cycles**
(`agent.max_cycles`, env `SHLEPA_MAX_CYCLES`, default 2) with a review
**relay** between cycles, and the only bounds are the fixed
per-operation constants (`shlepa_agent/budget.py`):

```
plan    = 30s per cycle
work    = 120s per cycle
review  = 45s (relay, between cycles only; SHLEPA_REVIEW_TIME)
bash    = 30s per call (also the tool max)
llm wall = 180s per request (open -> last chunk)
finalize reserve = 15s (SHLEPA_FINALIZE_RESERVE)
```

An explicit `[phases.<id>].time` overrides the regime cap for that phase
(dev/testing knob); the shipped config leaves plan/work/review unset so
the regime constants apply.

There is **NO global hard stop, NO request-start gate, NO token budget
and NO request-count limit** (issue #62): token usage is still logged
per request (telemetry / tie-break analysis) but never enforced. The run
ends exactly after the last WORK (its outcome decides the final status),
or when the container is killed at the task's own limit (the external
boundary).

## The hard cycle loop (v6-rewrite)

Every run walks exactly `max_cycles` plan → work cycles (phase ids:
`plan`, `work`, `review` — the review is the **relay**). The entry is
always `plan` (`agent.entry` is a dev knob to force `work`).

```
plan ──> work ──> review (relay) ──> plan ──> work ──> exit
              (cycle 1)      (between cycles only,   (cycle N = max_cycles)
                               toolless, typed)           the run ends here)
```

The plan has no shortcut around work: the `PlanResult` schema carries no
routing field, and the runner **always routes plan → work** (the plan phase
has no write tools and can never deliver anything).

| Phase      | Fresh/continued | Output         | Hard time cap | Retries | Reasoning |
|------------|-----------------|----------------|---------------|---------|-----------|
| `plan`     | fresh run (cycle ≥ 2: + previous work result + relay) | `PlanResult` (typed) | 30s (`SHLEPA_PLAN_TIME`) | 1 | — |
| `work`     | fresh run (gets the plan +, cycle ≥ 2, the relay) | `WorkResult` (typed) | 120s per cycle | 1 | — |
| `review`   | resumes the just-finished WORK transcript (trimmed) | `ReviewResult` relay (typed) | 45s (`SHLEPA_REVIEW_TIME`) | 0 | low |

Tool policy (`[tool_policy]` in `config.toml` — the single source of
truth; `[phases.*].tools` is only a legacy fallback for dev/test
configs): `plan` is read-only (`read`, `recon`, `search`); `work` gets
`read`, `write`, `edit`, `bash`, `recon`, `search`; `review` (relay) is
**toolless** (`[]`). Per-iteration overrides use `<phase>_c<N>` keys
(e.g. `work_c2`) — they only apply to that specific cycle.
`[tool_policy].disabled` lists the unrouted phases (`commit`, `repair`,
`salvage`, `emergency` — kept on disk for re-enable).

An explicit `[phases.*].time` overrides the regime cap for that phase
(dev/testing knob); the shipped config leaves them unset.

Routing rules (runner, v6-rewrite):

- **Hard cycles**: exactly `agent.max_cycles` (env `SHLEPA_MAX_CYCLES`,
  default 2) plan → work cycles run, unconditionally.
- A done `plan` (typed `PlanResult`, `goal`/`findings`/`steps`/`risks` —
  no routing field) **always** flows to WORK, even a trivial plan.
- `plan` timeout → one toolless `final_ask` on the plan conversation, then
  WORK. The final_ask is always typed: the model emits a `PartialHandoff`
  (objective, findings, files_seen, hypotheses, failed_paths, next_action,
  deliverable_path_if_known) and the harness independently extracts the
  deterministic LAST_TOOLS tail (last 6 tool calls with capped args and
  results, `SHLEPA_LAST_TOOLS_N`). Both land in the fresh WORK prompt —
  the full plan transcript is never carried (KV-cache: the final_ask
  prefix is byte-identical to the plan's last request).
- `plan` error (after retries) → WORK with a direct-execution note
  (there is no plan to follow).
- `work` returns a typed `WorkResult` (`summary`, `findings`,
  `deliverable`, `confidence`). The reported run output is the last
  work's `summary`.
- `review` (the relay) returns a typed `ReviewResult` (`summary`, `done`,
  `problems`, `hints_next`). It is **distillation only** — it never
  routes, never repairs, never decides the exit. Its full typed fields
  (summary + problems + "do next" list, plus a context note when
  `done=true`) reach the next cycle's PLAN and WORK prompts via the
  `previous_results` block.
- **Relay failure is not fatal**: a relay cut by its cap or failing after
  its retries is logged as `review_fallback` (`reason` `timeout` / `error`) and
  the next cycle starts without it.
- **The run ends after the last WORK**: the final status is the last
  work's outcome — `done` / `timeout` / `error`. A plan timeout or error
  in the last cycle never changes it by itself.
- **Cycle continuation**: after every cycle except the last, the relay
  runs (logged as a `cycle` event, `reason=relay`); the next cycle's PLAN
  receives the previous work result + the previous relay, and its WORK
  additionally receives the relay.
- **Phase hard timeouts** (`plan`/`work` cap expiry) and phase errors are
  hand-offs, not crashes. Work timeout: one toolless `final_ask` on the
  same conversation — "time is up, write the deliverable now, no tools" —
  capped at 30s, then the relay (between cycles) or the exit (last cycle).
  Plan timeout: one typed `final_ask` (partial hand-off), then WORK.
  Both requests reuse the phase's last request prefix byte-for-byte
  (KV-cache reuse on the local LLM server). The `final_ask` log event
  carries the `mode` (`partial` = typed hand-off, `off` = plain message).
- **Disabled phases** (kept on disk, never routed): `commit` (the v6
  reviewer/verifier — superseded by the relay + the mechanical exit
  gate), `repair`, `salvage` and `emergency`. Their phase classes,
  prompts and `[phases.*]` sections stay in the package for possible
  re-enable; `[tool_policy].disabled` is the routing gate.
- **Step guard** (`agent.max_steps` > 0, dev knob, off by default): once
  the number of phase runs reaches the cap, the run stops at the next
  BETWEEN-CYCLES boundary (final status `timeout`); it never stops in the
  middle of the last cycle.
- **Mechanical exit gate**: after the last work the runner runs the
  deliverable check (file/format/keys) and the test-file hash guard —
  pure mechanics, no LLM. Endpoint safety net: a persistent 429/402/5xx
  storm finalizes the run as `done` (`endpoint_finalized`).
- **Retries** apply to non-timeout errors only: `plan` 1, `work` 1,
  `review` 0. Timeout results (time caps, context-limit breaches) are
  never retried — they hand off per the rules above.
- **State hand-off**: after every phase the runner persists the run state
  (elapsed, cycles, regime, per-phase results) to the run-state file
  (`$SHLEPA_STATE_FILE`, default `/tmp/shlepa_state.json`) — never into
  the task workdir; the structured bridge between phases and cycles.

## Baseline tool policy (v5.1)

The packaged `config.toml` **is** the baseline (the `baseline` arm is a
no-op on top of it):

| Phase      | Tools                                                        | Notes |
|------------|--------------------------------------------------------------|-------|
| `plan`     | `read`, `recon`, `code_search`, `file_outline`               | maps and plans only — **no bash, no writes** |
| `work`     | `read`, `write`, `edit`, `bash`, `recon`, `code_search`, `file_outline` | the only phase with **bash** and the only phase that writes the deliverable |
| `commit`   | — (toolless)                                                 | the review judge; empty tool list, never augmented by arms/env |
| `emergency`| `read`, `write`, `edit`, `bash` (legacy, unused)             | arm additions still land here (deduped, harmless) |

- `recon` ships in the baseline, so the recon prompt block renders the
  **tool variant** (`recon_tool.md`) in the tooled phases; the toolless
  review renders no recon block at all. The script variant
  (`recon_script.md`) remains for phases without the recon tool (e.g. the
  read-only arm's phases).
- The arms are now **engine/variant switches on top of the baseline**:
  `+smart-grep` pins the search engine to `rg` (the baseline default),
  `+sifs` to SIFS, `+forensics`/`+mitre-kb` add their tool to every tooled
  phase, `+recon` is a no-op (recon is baseline), `read-only` replaces the
  tooled phases with read/write/edit + recon (no bash).

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
| `SHLEPA_CODE_SEARCH_TIMEOUT` | `tools.code_search.timeout` (per-call wall, default 30s) | float |
| `SHLEPA_PLAN_TIME` | `phases.plan.time` (default: plan cap 30s) | float |
| `SHLEPA_SEARCH` | `tools.search.enabled` | 1/0 (bool; 0 disables the search tool) |
| `SHLEPA_MAX_CYCLES` | `agent.max_cycles` | int ≥ 1: the hard plan/work cycle count (default 2) |
| `SHLEPA_REVIEW_TIME` | `phases.review.time` | float: relay cap override (default: regime 45s) |
| `SHLEPA_FINALIZE_RESERVE` | — (read directly by `budget.py`) | float: seconds reserved for finalization at run end (default 15) |
| `SHLEPA_REVIEW_SUBCAPS` | — (read directly by the phases) | 1/0: 1 (default) keeps the legacy commit/repair subcaps for the disabled phases; 0 restores the 45s envelope |
| `SHLEPA_LAST_TOOLS_N` | — (read directly by the harness) | int: how many last tool calls go into the LAST_TOOLS block (default 6, 0 disables) |

Model/endpoint variables are unchanged (set by the harness, not the
config): `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

### AGENT_CODE_SEARCH (deliberate `AGENT_*` exception)

Dev switch for the code-search engine (the legacy `AGENT_*` set was
dropped in v2; this one is wired on purpose). Values: `rg` (ripgrep
fixed-string scan) or `sifs` (bundled SIFS binary, BM25-offline;
`agent/tools/bin/sifs`). The baseline ships search **on** with the `rg`
engine; the switch only pins the engine. Unset or an invalid value: the
packaged baseline stays as-is (search on, `rg`), byte-identical to the
golden fixture (`agent/tests/fixtures/default_prompt.txt`). When set, the
config layer stores the engine (`code_search.engine`) and appends
`code_search` + `file_outline` to every tooled phase (deduped; the
toolless review is never augmented).
Engine resolution inside the tools: `rg` → the ripgrep scan; `sifs` →
BM25, or hybrid when the model asks (`mode="hybrid"`, needs the embedding
model, dev only); a missing/broken SIFS binary degrades to rg/regex with a
NOTE line (never crash). Each call runs under a per-call wall
(`tools.code_search.timeout`, default 30s — the v5 regime bash cap).
Shaped for the named toolset arms (#51): an arm is exactly this config
mutation.

## Bounds: hard vs advisory

- **Hard, enforced by `TrackedModel`** (per request, no horizon):
  the open timeout `request_timeout = 180s` and the wall cap
  `llm_wall = 180s` (open -> last chunk). There is NO hard stop, NO
  request-start gate, NO request-count limit and NO token budget.
- **Hard, enforced by the runner**: the fixed per-phase time caps (plan
  30s / work 120s / review 45s; `[phases.*].time` overrides), the hard
  cycle count (`SHLEPA_MAX_CYCLES`) and the optional step guard.
- **Hard, enforced by the environment**: the container kill at the
  task's own time limit — the only external bound on the cycles.
- **External budget — developer-owned, never agent-visible**: each task
  has an official **time limit** (the container kill) and **token limit**
  (contest README: *"Each task has its own token and time limits"*). The
  budget value is unknown to the agent runtime — T is not exposed
  (issue #63) and the token limit is not surfaced at all — and may be
  configured per task by the developer. A global deadline or a global
  token budget inside the agent would therefore be pure guessing — there
  is no point in them. The system accounts for the budget without the
  agent ever knowing about it:
  - *system side*: every operation that can run a long time or forever is
    capped locally (the caps above — phase caps, bash 30s, LLM wall 180s,
    file tools 5s, code_search 30s per call); per-phase token metrics are
    logged to MLflow so the developer can watch consumption against the
    budget; and the work phase keeps the deliverable file fresh on disk,
    so whichever external cut happens first, a partial deliverable —
    never an empty one — is what scores;
  - *agent side*: the agent's prompt mentions only local per-operation
    caps — never external limits, remaining budget, or budget pressure.
    No prompt, tool output, or phase message may tell the agent it is
    tight on budget. (The legacy `emergency` phase, unused in v5, was
    reworded to carry no deadline language for the same reason.)
- **Advisory (rendered into prompts/status, never enforced)**:
  per-phase `soft_time`/`soft_tokens` (`plan`: 25s/15k, `work`: 105s — no
  token note for work, `commit`: 35s/20k; every soft time stays under its
  phase's hard cap) and `phases.*.requests` (legacy slices, no longer
  enforced — kept as prompt context only).

## Sections overview

- `[agent]` — pipeline entry (dev knob, default `plan`), temperature
  (opt-in: sent to the endpoint only when `send_temp` is enabled; default:
  not sent, the endpoint decides), `max_cycles` (the hard plan/work cycle
  count, default 2), step guard (dev knob), emergency phase name (unused —
  emergency is disabled).
- `[tool_policy]` — the single source of truth for per-phase tool
  surfaces (`phases.<id>` lists; `<phase>_c<N>` per-cycle overrides) and
  the `disabled` list of unrouted phases. Legacy `[phases.*].tools` is
  only a fallback for configs without `[tool_policy]`.
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
| `agent_start` | `model`, `base_url`, `workdir`, `prompt`, `entry` | first line of a run (the stable CLI fields stay; `temp` is present only when `agent.send_temp` is enabled). Additive (v6-rewrite): `emergency`, `max_steps`, `max_cycles`, `plan_cap`, `work_cap`, `review_cap`, `bash_cap`, `llm_wall` (CLI ignores unknown fields; there is NO `t`/`t_source`/`hard_time`/`soft_time`/`commit_deadline`) |
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
| `cycle` | `reason`, `cycle`, `elapsed_s` | a review relay finished between cycles (`reason=relay`) — the next plan/work cycle is about to start |
| `review_fallback` | `reason`, `valid`, `elapsed_s` | the relay was cut (`timeout`) or failed (`error`); the next cycle starts without it |
| `budget` | `reason`, `elapsed_s` (+ `detail`) | regime hand-off (`regime` logs the fixed caps at startup; `<phase> time cap`, `max_steps`, …) |
| `deliverable_check` | `kind`, `path`, `exists`, `non_empty`, `parse_ok`, `keys_ok`, `valid`, `reason` | the mechanical exit gate after the last work (no LLM) |
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
