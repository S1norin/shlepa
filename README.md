# Shlepa

Universal security agent for the
[Universal Agent Competition](https://github.com/SecureIntelligent/UniversalAgenticCompetitionPublic)
(SecureIntelligent). Shlepa is a closed LLM agent that solves cybersecurity
tasks: vulnerability finding, SWE-bench-style fixes, forensics, CTF-style
challenges.

This repository is the development workspace: agent source, developer
tooling (`shlepa` CLI), the task pool, experiment presets, telemetry
infrastructure, and research notes.

## Repository layout

| Path            | Contents                                                                                                    |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| `agent/`        | Agent source (the submission). pydantic-ai baseline, `run.sh` entrypoint, env-gated OTel `telemetry/`        |
| `cli/`          | Developer tooling: the `shlepa` command (`run`, `smoke`, `doctor`, `zip`, `submit-test`, `clean`, `task`)    |
| `tasks/`        | Task pool in Harbor format, `<source>-<slug>` layout — registry in `tasks/README.md`                         |
| `experiments/`  | Experiment presets for `shlepa run <preset>` (task subset, model, agent params)                             |
| `otel/`         | Dev telemetry collector (OpenTelemetry + Jaeger, docker compose)                                            |
| `docs/`         | `tasks.md` (task format), `runbook.md` (operations), `known_issues/`                                        |
| `research/`     | `papers/` (PDFs) + `notes/` (digests). The backlog lives in GitHub issues, not here                         |
| `tmp/`          | Timestamped dev workspaces (gitignored, cleaned by `shlepa clean`)                                          |
| `.pi/`          | Dev-agent (pi) configuration: extensions, `AGENTS.md`, repo-local skills                                    |

## Quickstart

```bash
# 1. Prerequisites: uv, docker, git (see docs/runbook.md)
# 2. Configure
cp .env.example .env   # then fill in real values

# 3. Install the CLI project (pulls the agent project as a path dependency)
uv sync --project cli

# 4. Verify the environment
shlepa doctor

# 5. End-to-end smoke test (trivial task, real LLM call, MLflow run)
shlepa smoke

# 6. Run an experiment preset (default: all local tasks)
shlepa run all

# 7. Build the contest submission (<= 10 MB, no telemetry)
shlepa zip
```

## Rules

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules (branching,
commits, pre-PR checks) and [docs/runbook.md](docs/runbook.md) for the
full operations guide.
