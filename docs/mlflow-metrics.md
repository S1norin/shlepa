# Agent measurement schema v2

Each trial is a run in its benchmark-family experiment (`run_kind=trial`).
`shlepa run` creates the run before execution and closes it after logging.
The execution ID is allocated before the agent starts and is propagated to its
root trace as `shlepa.execution_id`. Existing trace routing is unchanged.

## Outcomes

- `solved`: binary benchmark success; filter by `evaluation_valid` for graded success rates.
- `reward`: finite numeric verifier output in [0, 1], including partial credit.
  Missing, malformed, infinite or out-of-range output is not a zero reward.
- `evaluation_valid`: whether the verifier produced an interpretable result.
- `grader_status`: `scored`, `missing_reward`, `invalid_reward`, `grader_error`,
  `missing_verifier`, or other explicit setup/pytest failure categories.
- `termination_reason`: agent completion, budget, timeout, crash or error.

A valid zero reward is a completed evaluation, not an MLflow failure. A technical
failure is `FAILED`. An agent timeout with a valid verifier result remains a
measured attempt. A grader error is recorded separately and does not overwrite
usage already collected from the agent. Harbor imports retain `harbor_status`
and use the same reward/validity fields; an absent Harbor reward is unavailable,
not an inferred timeout penalty. Reports must show invalid attempts explicitly.

## Resource and behavior measurements

Existing `tokens_in`, `tokens_out`, `tokens_total`, cache counts and phase-token
metrics remain available. `tokens_reasoning` is recorded only when reported and
is not added again to output tokens. SDK cache defaults do not prove provider
reporting, so `cache_usage_status=unknown`; legacy zero counters must not be
interpreted as proof that the provider did not use cache.

`usage_status=unknown` means no usage was observed; `partial` means usage reports
were observed but completeness across failed/streaming requests is not proven.
Harbor's `reported` indicates that both aggregate counters were supplied, not
that billing completeness was independently verified.

Additional measured counters:

- `llm_requests`: upstream request attempts, including retries.
- `llm_errors`: errors observed while opening/requesting or consuming an upstream response.
- `llm_retries`: automatic upstream retries, excluding phase retries.
- `usage_reports`: observed usage events (not a substitute for request count).
- `tool_errors`: tools explicitly reporting a failure through the result formatter.
- `tool_timeouts`: explicitly reported bash timeouts.
- `tool_validation_retries`: Pydantic AI retry prompts for tool results; these can
  include tool-requested retries, not only malformed arguments.
- `phase_executions`, `phase_retries`, `budget_events`.
- `phase_duration_sec.<phase>` and `tool_duration_sec.<tool>`: summed elapsed
  time; concurrent operations can overlap and their sum is not wall-clock time.

`duration_sec` remains total runner time. New `agent_duration_sec`,
`setup_duration_sec`, and `grader_duration_sec` measure their respective scopes,
including failed calls. Copy-out and cleanup remain part of total time only.
A scope that never ran has no duration metric.

## Configuration and artifacts

Tags identify schema version, task, execution, batch, model, version, endpoint
class, termination and measurement availability. Params include task/grader
hashes, agent source hash, timeouts and runner mode. The resolved agent configuration is captured
inside the executing agent together with the active budget regime, stored in `data/configuration.json`, and hashed as
`config_hash`. Unavailable configuration has an explicit tag; it must not be
assumed equivalent to a known configuration.

Full final output, error, grader detail and `result.json` are artifacts under
`data/`. Final output and errors are no longer truncated into params. No process
environment or credentials are copied into the configuration snapshot.

## Batch summaries

```bash
uv run --project cli --no-sync shlepa metrics-summary BATCH_ID [BATCH_ID ...]
```

This reads existing trial runs and creates summary runs in their respective
experiments (`run_kind=batch_summary`). Model, git revision, configuration,
endpoint class and toolset are grouped separately. Different revisions of the
same task/grader cannot be combined. The summary retains source run IDs and
batch IDs in `summary.json`; rerunning creates a new analysis run.

Reported metrics include attempt counts, valid/invalid counts, micro success
rate, task-balanced macro success rate, mean reward, and agent duration p50/p95
with sample count. Invalid evaluations are excluded from graded success rate
but remain visible in counts. Low sample counts make p95 unstable.

## Deliberately unavailable measurements

Pricing cannot be inferred reliably for custom endpoints, so no fabricated
USD cost is logged. Billing-aware cost needs explicit versioned tariffs and
provider-normalized cache/usage semantics. Generic LLM judges, task-specific
precision/recall, pass@k/pass^k estimates, confidence intervals and paired A/B
inference require an explicit evaluation protocol and/or ground truth. They
are not inferred from a single batch. Trace assessments and per-family graders
can be added without changing this trial schema.
