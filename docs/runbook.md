# Shlepa Runbook

Day-to-day operations for the Shlepa development workspace: setup, the day-1
flow, the full command reference, CI secrets, and troubleshooting.

## Prerequisites

- `uv` (package manager; installs Python 3.12 into project venvs)
- `docker` (CLI + a running daemon) — task environment images run in containers
- `git` — the repo is the single source of truth for the submission
- `gh` — optional, used by the `.pi` skills (github-issues, backlog)
- A reachable LLM endpoint (OpenAI-compatible chat API) and its model name
- A reachable MLflow server (this project uses the remote server with basic auth)

## Setup

```bash
# from the repo root
uv sync --project agent
uv sync --project cli --group dev

# configure the environment
cp .env.example .env
# edit .env: OPENAI_BASE_URL, OPENAI_API_KEY, LOCAL_AGENT_MODEL,
# MLFLOW_TRACKING_URI, MLFLOW_TRACKING_USERNAME, MLFLOW_TRACKING_PASSWORD

# start the local telemetry stack (collector + Jaeger UI on :16686)
docker compose -f otel/docker-compose.yml up -d

# sanity check: exit 0 means everything is wired correctly
uv run --project cli shlepa doctor
```

## Day-1 flow

```bash
# 1. environment is healthy (endpoint, model name, MLflow, docker)
uv run --project cli shlepa doctor

# 2. end-to-end check: one real task, result logged to MLflow
uv run --project cli shlepa smoke

# 3. a dev run over a preset (experiments/<name>.yaml; 'all' = every task)
uv run --project cli shlepa run all

# 4. see the agent's traces in Jaeger (with telemetry enabled)
SLEPA_OTEL_ENABLED=1 uv run --project cli shlepa run all
uv run --project cli python otel/check_trace.py
```

`shlepa run` prints an MLflow URL per task; the summary table shows
solved/duration/tokens. Workspaces land in `tmp/<YYYYMMDD-HHMMSS>-<slug>/`.

Runs are logged into the MLflow experiment named after the **task family**
derived from the slug — `bench-<x>-*` → `bench-<x>` (e.g. `bench-soc`,
`bench-ctf`), `contest-*` → `contest`, anything else → first dash component
(fallback `misc`). The preset is kept as a tag, so you can still filter
runs by preset. Legacy preset-named experiments (`all`, `ctf`, …) are
untouched history; `shlepa-ci` and `smoke` keep their fixed experiments.

## Command reference

All commands run from the repo root via `uv run --project cli shlepa ...`.

| Command | Purpose | Example |
| --- | --- | --- |
| `run [preset]` | Dev-engine run over a preset (default `all`); agent in container, real task env | `shlepa run all` |
| `run --dry-run [preset]` | Print resolved tasks + model, execute nothing | `shlepa run --dry-run all` |
| `smoke` | Doctor + one real task + MLflow visibility check; exit 0/1 | `shlepa smoke` |
| `smoke --ci` | Same, but the secondary CI endpoint and the `shlepa-ci` experiment | `shlepa smoke --ci` |
| `doctor` | Hard checks: endpoint, model name, MLflow, MLflow OTLP ingestion (when `SLEPA_OTEL_ENABLED=1`), docker | `shlepa doctor` |
| `doctor --probe` | Additionally one chat completion, prints the self-reported model | `shlepa doctor --probe` |
| `zip` | Build `dist/submission-<sha>.zip` (<= 10 MB, no telemetry) | `shlepa zip` |
| `zip --register` | Also register the submission as a new version of the `shlepa` MLflow model | `shlepa zip --register` |
| `trace-export --batch <id>` | Export the batch's agent traces from MLflow: manifest + JSON + digests + summary | `shlepa trace-export --batch <id>` |
| `submit-test [tasks...]` | Contest-faithful check: unzipped submission runs inside Harbor | `shlepa submit-test contest-hello-file` |
| `submit-test --ci [tasks...]` | Same, CI endpoint + `shlepa-ci` experiment; no args = all tasks | `shlepa submit-test --ci` |
| `task new <source>-<slug>` | Scaffold a new local task under `tasks/` | `shlepa task new own-math-101` |
| `clean [--days N]` | Remove `tmp/` workspaces older than N days (default 7) | `shlepa clean --days 14` |
| `help [topic]` | Short help; `shlepa help task` for task conventions | `shlepa help task` |

## CI secrets

All six secrets are set in the GitHub repo settings (Settings -> Secrets and
variables -> Actions). Values come from `.env`; never write them into files or
commits.

| Secret | Purpose | Used by |
| --- | --- | --- |
| `CI_OPENAI_BASE_URL` | Secondary (weaker/cheaper) LLM endpoint for CI | `pr-checks`, `main-full` |
| `CI_OPENAI_API_KEY` | API key for the CI endpoint | `pr-checks`, `main-full` |
| `CI_MODEL` | Model name on the CI endpoint | `pr-checks`, `main-full` |
| `MLFLOW_TRACKING_URI` | Remote MLflow server URI | `pr-checks`, `main-full` |
| `MLFLOW_TRACKING_USERNAME` | MLflow basic-auth user | `pr-checks`, `main-full` |
| `MLFLOW_TRACKING_PASSWORD` | MLflow basic-auth password | `pr-checks`, `main-full` |

Workflows: `pr-checks` (on every PR: zip build, flake8, `shlepa smoke --ci`)
and `main-full` (on push to main touching `tasks/` or `agent/`:
`shlepa submit-test --ci` over all local tasks). Results land in the
`shlepa-ci` MLflow experiment with `endpoint_class=ci`.

## Troubleshooting

**`doctor` fails on the model check (exit 2).** The endpoint's `/models` list
does not contain `LOCAL_AGENT_MODEL`. Either the model is not loaded on the
server or the name in `.env` is wrong — check with `shlepa doctor --probe`
(which prints the model name the server reports for a chat completion) and
`curl {OPENAI_BASE_URL}/models`.

**OTel spans do not appear in Jaeger.** Make sure the collector is up
(`docker compose -f otel/docker-compose.yml ps`), the run was started with
`SLEPA_OTEL_ENABLED=1`, and `OTEL_EXPORTER_OTLP_ENDPOINT` points at the
collector (default `http://localhost:4318`). Dev runs execute the agent
inside the task container, which uses the host network, so `localhost`
refers to the dev machine. Give exports a few seconds, then run
`uv run --project cli python otel/check_trace.py` — it prints the latest
trace id or tells you exactly which assertion failed.

**Task container build pulls `secureintelligent/acp:latest` slowly (or fails).**
The dev images are built on top of the contest agent image; the first
`shlepa run` / `shlepa submit-test` pulls it. If the pull fails, warm it
manually: `docker pull secureintelligent/acp:latest`. If your network
requires a registry mirror, configure docker's mirror settings — the image
name itself must not change (task Dockerfiles reference it).

**MLflow auth errors (401/403).** Verify `MLFLOW_TRACKING_USERNAME` and
`MLFLOW_TRACKING_PASSWORD` in `.env`, and that the URI uses `https`
(the server rejects plain `http`). A quick manual check:
`curl -u $MLFLOW_TRACKING_USERNAME:$MLFLOW_TRACKING_PASSWORD "$MLFLOW_TRACKING_URI/api/2.0/mlflow/experiments/get-by-name?experiment_name=Default"`.

**`shlepa zip` fails the size check.** The submission must stay <= 10 MB.
The zip already excludes `telemetry/`, tests, and dev metadata — the usual
culprit is a large vendored file under `agent/`. Check what bloated it:
`python -m zipfile -l dist/submission-*.zip`.

**Agent run times out.** `[agent] timeout_sec` in the task's `task.toml`
bounds the agent; the engine adds a buffer and then kills the container.
A timeout is logged as an unsolved run (not a crash). Increase the timeout
deliberately; do not silence it.

**Missing traces after a run.** `shlepa run` prints a warning when the
collector's health endpoint (`http://127.0.0.1:13133/`) is unreachable,
but if the trace still does not show up, work through this checklist:

1. **Collector down?** `docker compose -f otel/docker-compose.yml ps` and
   `curl -s http://127.0.0.1:13133/` — if it is down, the agent's spans
   were lost (the agent never buffers to disk); rerun the batch.
2. **MLflow exporter failing?** `docker logs --tail 100 otel-otelcol-1`
   — look for `otlp_http/mlflow` export errors (auth, body-size, TLS).
   Traces may still be in Jaeger even when the MLflow export fails.
3. **Local copy?** `uv run --project cli python otel/check_trace.py
   --backend jaeger` — Jaeger is the other half of the dual export and
   keeps an in-memory copy (capped at 100k traces, lost on restart).
4. **Async lag?** The collector exports to the remote server
   asynchronously; wait a minute and retry `shlepa trace-export
   --batch <id>`.
5. **Jaeger restarted?** Jaeger v2 keeps its local copy in memory (capped
   at 100k traces); a restart of the `jaeger` container wipes it. The
   remote MLflow experiment is the durable copy.

Note: a hard `exec_timeout` kills the container; most spans are already
flushed (batch processor), and every span now carries `shlepa.batch_id`
so the trace still correlates by batch even if the `agent.run` root span
never made it.
