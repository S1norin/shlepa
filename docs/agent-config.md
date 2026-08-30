# Agent configuration (v2)

The v2 agent reads all tuning values from a single file:

```
agent/shlepa_agent/config.toml
```

The file ships inside the package, so the submission zip carries it
automatically. Environment variables (`SHLEPA_*`) override individual keys
at runtime; **invalid env values are ignored** (the file value wins).

## Env-var overrides

| Env var | Config key | Type |
|---|---|---|
| `SHLEPA_TEMP` | `agent.temp` | float |
| `SHLEPA_MAX_STEPS` | `agent.max_steps` | int |
| `SHLEPA_BUDGET_HARD_TIME` | `budget.hard_time` | float |
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
| `SHLEPA_COMMIT_TIME` | `phases.commit.time` | float |
| `SHLEPA_COMMIT_REQUEST_LIMIT` | `phases.commit.requests` | int |
| `SHLEPA_COMMIT_REASONING_EFFORT` | `phases.commit.reasoning_effort` | str |

Model/endpoint variables are unchanged (set by the harness, not the config):
`OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LOCAL_AGENT_MODEL`.

## Migration from the legacy `AGENT_*` env vars (v1)

The v1 `AGENT_*` environment variables were **dropped** with the v2
architecture. Old name → new location:

| v1 env var (default) | v2 config key in `config.toml` | v2 env override |
|---|---|---|
| `AGENT_TEMP` (0.2) | `agent.temp` | `SHLEPA_TEMP` |
| `AGENT_HARD_TIME` (585.0) | `budget.hard_time` | `SHLEPA_BUDGET_HARD_TIME` |
| `AGENT_SOFT_TIME` (500.0) | `budget.soft_time` | `SHLEPA_BUDGET_SOFT_TIME` |
| `AGENT_REQUEST_LIMIT` (90) | `budget.request_limit` | `SHLEPA_BUDGET_REQUEST_LIMIT` |
| `AGENT_TOKEN_BUDGET` (300000) | `budget.token_budget` | `SHLEPA_BUDGET_TOKEN_BUDGET` |
| `AGENT_MAX_TOKENS` (16384) | `budget.max_tokens` | `SHLEPA_BUDGET_MAX_TOKENS` |
| `AGENT_REQUEST_TIMEOUT` (180.0) | `budget.request_timeout` | `SHLEPA_BUDGET_REQUEST_TIMEOUT` |
| `AGENT_REQUEST_WALL` (240.0) | `budget.request_wall` | `SHLEPA_BUDGET_REQUEST_WALL` |
| `AGENT_BASH_TIMEOUT` (120.0) | `tools.bash.timeout` (v2 default is 30; hard cap `tools.bash.max_timeout` = 120) | `SHLEPA_BASH_TIMEOUT` / `SHLEPA_BASH_MAX_TIMEOUT` |
| `AGENT_MAX_TOOL_OUTPUT` (16000) | `tools.bash.max_output` (+ `tools.read.max_output`, 4000) | `SHLEPA_BASH_MAX_OUTPUT` / `SHLEPA_READ_MAX_OUTPUT` |
| `AGENT_COMMIT_TIME_CAP` (80.0) | `phases.commit.time` | `SHLEPA_COMMIT_TIME` |
| `AGENT_COMMIT_REQUEST_LIMIT` (25) | `phases.commit.requests` | `SHLEPA_COMMIT_REQUEST_LIMIT` |
| `AGENT_COMMIT_REASONING_EFFORT` ("low") | `phases.commit.reasoning_effort` | `SHLEPA_COMMIT_REASONING_EFFORT` |

Notes:

- `AGENT_MAX_TOOL_OUTPUT` was a global cap in v1; in v2 it is per-tool
  (`bash.max_output` = 16000, `read.max_output` = 4000). `read` also caps the
  number of lines per call (`read.max_limit` = 100); `bash` takes a per-call
  timeout clamped to `[1, max_timeout]`.
- Phase request slices live per phase now: `phases.explore.requests` (90)
  and `phases.commit.requests` (25). The global `budget.request_limit`
  stays as the cross-phase guard.

## Sections overview

- `[agent]` — pipeline entry, emergency phase, step guard, temperature.
- `[budget]` — global wall-clock/token/request budgets (TrackedModel).
- `[tools.*]` — per-tool `enabled` plus caps: `timeout`/`max_timeout`/`max_output`
  (bash), `max_limit`/`max_output` (read).
- `[phases.*]` — per-phase toolset, request/time slices, reasoning effort,
  retry count, template wrapper overrides.
- `[template]` — ordered block list + per-block wrappers for the common
  request template.

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

- `spent` — tool wall time; `ended_at` — seconds into the run (the same clock
  as the global budget); `time_left` — until `budget.hard_time`.
- `FAILED:` is emitted only on tool failure (e.g. file not found, edit
  validation error, bash spawn error / timeout kill). Non-zero bash exit codes
  stay plain output — the model sees `[exit_code]` in the body.
- The `UNTRUSTED TEXT` block marks environment data (file content, command
  output) as data, not instructions (anti-prompt-injection). `write`/`edit`
  return status lines without the block.
- Long argument values in the header are truncated to 200 chars.
