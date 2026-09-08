# Shlepa dev-agent instructions

Repository for **Shlepa** — a security agent for the Universal Agent
Competition. Conversation with the user in their language; **all repo
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
| `shlepa run [preset] [--dry-run] [--arm <arm>]` | dev experiment loop: per task build env+dev images, run the agent **inside** the container (`/app`, `--network host`), score via `tests/test.sh` → `reward.txt`, log to MLflow (runs tagged `batch_id`/`mlflow_trace_id` when telemetry is on). `SLEPA_NO_DOCKER=1` switches to the legacy host-agent mode. `--arm <arm>` selects a named toolset arm on top of the baseline (the packaged config, which ships `recon` + code search (rg engine) in plan/work and a read-only review (read + search, no bash)): `baseline` (no-op); `+smart-grep` (pin code_search to ripgrep); `+sifs` (code_search over SIFS); `+forensics` (log_triage); `+mitre-kb` (mitre_kb tool + KB index prefix); `+recon` (no-op — recon is baseline; the recon prompt block is the tool variant in the tooled phases); `read-only` (read/write/edit + recon, no bash) — the registry in `agent/shlepa_agent/toolsets.py` is the single source); flag > `AGENT_TOOLSET` env > `baseline`, passed into the container as `AGENT_TOOLSET`, and every MLflow run is tagged `toolset=<arm>`. |
| `shlepa trace-export --batch <id>` | export a batch's agent traces from the MLflow trace experiment: `manifest.jsonl`, per-task trace JSON + Markdown digests, `summary.md` (LLM-readable failure analysis). |
| `shlepa search-bench [--families …] [--engines …]` | research harness: measure search engines (read-all baseline, rg, sifs bm25) on the annotated query set (`research/code_search/analysis/queries.json`) plus a generated 10k-file corpus; emits a CSV + markdown report to `research/code_search/analysis/`. |
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
  PRs target **`dev`** by default (`dev` is the integration branch;
  `main` only when a change must land there directly).
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

- Experiment name = task **family** derived from the slug
  (`bench-<x>-*` → `bench-<x>`, `contest-*` → `contest`, otherwise the
  first dash component, fallback `misc`); run name = task display name;
  metrics: `duration_sec`, `tokens_in/out/total`,
  `tokens_cache_read`/`tokens_cache_write` (0 when the endpoint does not
  report cache), per-phase `tokens_in.<phase>`/`tokens_out.<phase>`/
  `tokens_cache_read.<phase>` (only for phases that ran; the sum of
  `tokens_in.<phase>` equals `tokens_in`), `tool_calls`, `solved`;
  tags: `preset`, `model`, `agent_version`, `git_sha`, `endpoint_class`
  (the preset stays a tag, so preset-scoped filtering still works).
  Legacy preset-named experiments (`all`, `ctf`, `socbench`, …) are kept
  untouched as history — only new runs use family naming.
- CI and smoke log to a dedicated experiment **`shlepa-ci`** / `smoke`
  (`endpoint_class=ci` for CI) via an explicit experiment override.
- Registered model **`shlepa`**: one version per submission
  (`shlepa zip --register`), artifacts = submission zip + full agent
  source tarball, tags `git_sha`/`model`.
- Telemetry data flow: `SLEPA_OTEL_ENABLED=1` makes every agent run
  export its spans via OTLP to the local collector in `otel/`
  (`docker compose -f otel/docker-compose.yml up`), which dual-exports:
  Jaeger (UI :16686, local debugging) **and** the remote MLflow server
  (OTLP/HTTP `POST /v1/traces`, durable) into the trace experiment
  **`shlepa-traces`**. Credentials live in gitignored `otel/.env`, never
  in the agent. `otel/check_trace.py` verifies either backend
  (`--backend jaeger|mlflow`); `shlepa doctor` probes MLflow OTLP
  ingestion when telemetry is on.
- Run ↔ trace correlation: `shlepa run` prints a `batch` id and tags its
  MLflow runs with `batch_id` + `mlflow_trace_id`; the agent's root span
  carries `shlepa.batch_id`/`shlepa.preset`/`git.commit`/`task` and, when
  the run doesn't finish cleanly, `shlepa.termination_reason`
  (`timeout`/`crash`). The root span also accumulates the run's token
  totals: `shlepa.llm.cumulative_prompt_tokens`/
  `shlepa.llm.cumulative_completion_tokens`/
  `shlepa.llm.cumulative_cache_read_tokens`/
  `shlepa.llm.cumulative_cache_write_tokens` (cache attributes only when
  non-zero). Each phase runs under a phase-labeled
  `invoke_agent <phase-id>` span carrying the phase's cumulative
  `gen_ai.aggregated_usage.*` token attributes.
- Per-phase metrics in a run come from usage events tagged with the
  phase id by the runner (`runner.py` sets it on the shared model before
  each phase); the same phase names appear in the trace spans, so the
  MLflow per-phase metrics and the trace-export per-phase table can be
  cross-checked.
- Second-LLM analysis workflow: `shlepa trace-export --batch <id>` writes
  `manifest.jsonl` (one line per task: state, tokens, `tokens_cache_read`
  and `phase_tokens` when available, signal tags),
  per-task `traces/<task>.json` (full dump) and `digests/<task>.md`
  (compact timeline, cache-read + per-phase token summary, failure
  signals), plus `summary.md`. Feed the
  analysis LLM the **manifest + digests first** (cheap, one context each);
  pull the full `traces/<task>.json` only for tasks flagged in the
  manifest (loop / tool_errors / repeated_results signals, or state !=
  OK). Details in `otel/README.md`.

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
