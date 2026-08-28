# Shlepa dev-agent instructions

Repository for **Shlepa** — a security agent for the Universal Agent
Competition. Conversation with the user is in Russian; **all repo
files, code, comments, docs and commit messages are in English**.

## Repo map

- `agent/` — the agent package (submission source): `agent.py` entry,
  `run.sh` entrypoint, `shlepa_agent/` package (`core.py`,
  `telemetry/` — dev-only, excluded from the zip). uv project, Python 3.12.
- `cli/` — `shlepa` dev CLI (typer): run engine, doctor, smoke, zip,
  task scaffolding, MLflow client. Depends on `agent/` as an editable path dep.
- `tasks/` — vendored/own contest tasks (Harbor / schema 1.2); registry in
  `tasks/README.md`, format in `docs/tasks.md`.
- `experiments/` — run presets (`all.yaml`: every discoverable task).
- `otel/` — local OpenTelemetry collector + Jaeger stack (docker compose).
- `docs/` — documentation (`tasks.md`, `known_issues/`).
- `research/` — paper notes and links (`notes/`, `papers/`).
- `tmp/` — per-run workspaces (`<timestamp>-<slug>/`), gitignored, cleaned by `shlepa clean`.
- `dist/` — built submission zips, gitignored.

## shlepa commands

| command | what it does |
|---------|--------------|
| `shlepa doctor [--probe]` | hard env checks (LLM endpoint + model match, MLflow, docker); `--probe` sends one real LLM request. Exit 0/1/2. |
| `shlepa run [preset] [--dry-run]` | dev experiment loop: per task build env+dev images, run the agent **inside** the container (`/app`, `--network host`), score via `tests/test.sh` → `reward.txt`, log to MLflow (runs tagged `batch_id`/`mlflow_trace_id` when telemetry is on). `SLEPA_NO_DOCKER=1` switches to the legacy host-agent mode. |
| `shlepa trace-export --batch <id>` | export a batch's agent traces from the MLflow trace experiment: `manifest.jsonl`, per-task trace JSON + Markdown digests, `summary.md` (LLM-readable failure analysis). |
| `shlepa smoke` | fail-fast end-to-end check: doctor → `contest-hello-file` → MLflow run exists. Exit 0/1. |
| `shlepa submit-test [--ci]` | strict contest-faithful test via Harbor inside the acp container (planned in CI). |
| `shlepa zip [--register]` | build the flat submission zip (telemetry/tests/pyproject stripped, ≤10MB); `--register` logs it + full source tarball to MLflow and creates a `shlepa` model version. |
| `shlepa clean [--days N]` | remove `tmp/` workspaces older than N days (default 7). |
| `shlepa task new <source>-<slug>` | scaffold a task (source: `contest`/`bench`/`own`). |
| `shlepa help [cmd]` | usage reference. |

Run everything from the repo root with `uv run --project cli --no-sync`
(the `shlepa` console script is available in `cli/`'s venv).

## .env variables

See `.env.example` for the full list; `.env` itself is gitignored.

- `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `LOCAL_AGENT_MODEL` — main LLM
  endpoint used by dev runs and the agent.
- `CI_OPENAI_BASE_URL` / `CI_OPENAI_API_KEY` / `CI_MODEL` — secondary
  (weaker) endpoint used by CI.
- `MLFLOW_TRACKING_URI` / `MLFLOW_TRACKING_USERNAME` /
  `MLFLOW_TRACKING_PASSWORD` — MLflow tracking (remote server; tests use
  a hermetic `file://` store).
- `SLEPA_OTEL_ENABLED` — `1` turns on OTel span export from the agent
  (dev only; the submission never sets it).
- `OTEL_EXPORTER_OTLP_ENDPOINT` — default `http://localhost:4318` (the
  local collector from `otel/`).
- `SLEPA_NO_DOCKER=1` — legacy host-agent run mode (experimental).

## Rules

- **English only** in everything committed.
- **No direct pushes to `main`** except the one-time documented
  bootstrap (already done). Feature branch + PR; branches
  `feature/<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`.
- Small commits, one logical change, **Conventional Commits**
  (`feat(agent): …`, `fix(cli): …`, `docs: …`, `test(tasks): …`, `chore: …`).
- Before a PR: `shlepa smoke` and `shlepa zip` must pass locally.
- Adding a task: scaffold with `shlepa task new`, update the
  `tasks/README.md` registry and `task.toml` provenance (see
  `docs/tasks.md`).
- `tmp/` workspaces are named `<timestamp>-<slug>`; never put
  long-lived data there.
- **Backlog = GitHub issues** — track work there, not in this file.

## MLflow / OTel overview

- Experiment name = preset name (e.g. `all`); run name = task display
  name; metrics: `duration_sec`, `tokens_in/out/total`, `tool_calls`,
  `solved`; tags: `preset`, `model`, `agent_version`, `git_sha`,
  `endpoint_class`.
- CI logs to a dedicated experiment **`shlepa-ci`**
  (`endpoint_class=ci`).
- Registered model **`shlepa`**: one version per submission
  (`shlepa zip --register`), artifacts = submission zip + full agent
  source tarball, tags `git_sha`/`model`.
- Telemetry: the local collector stack in `otel/`
  (`docker compose -f otel/docker-compose.yml up`); with
  `SLEPA_OTEL_ENABLED=1` every agent trace is dual-exported: Jaeger
  (UI :16686, local debugging) **and** the remote MLflow server
  (OTLP/HTTP `POST /v1/traces`, durable) into the trace experiment
  **`shlepa-traces`** (credentials live in gitignored `otel/.env`, never
  in the agent). `otel/check_trace.py` verifies either backend
  (`--backend jaeger|mlflow`); `shlepa doctor` probes MLflow OTLP
  ingestion when telemetry is on. `shlepa run` tags its MLflow runs with
  `batch_id` + `mlflow_trace_id`; `shlepa trace-export --batch <id>`
  exports a batch's traces as manifest/JSON/digests for offline LLM
  analysis (see `otel/README.md`).

## CI secrets (GitHub Actions)

`CI_OPENAI_BASE_URL`, `CI_OPENAI_API_KEY`, `CI_MODEL`,
`MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`,
`MLFLOW_TRACKING_PASSWORD`.

## Danger zones

- **Never commit `.env`** (or any secret). It is gitignored — if it
  ever appears in a diff, stop and fix.
- **Never add OpenTelemetry dependencies to the agent base
  environment** (`agent/pyproject.toml` core deps). Telemetry is the
  optional `[telemetry]` extra; the submission zip must not contain
  `agent/shlepa_agent/telemetry/`.
- **Never modify `agent/agent.py`** except during a deliberate upstream
  sync (it must stay byte-identical to the contest baseline).
- **Never break the ≤10MB submission zip** — check size in the zip
  step; add to the exclusion list before adding big files.
- Do not push directly to `main` (see Rules).
