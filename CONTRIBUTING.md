# Contributing to Shlepa

## Branching and commits

- **No direct pushes to `main`.** Work on a branch, open a PR.
  Exception: the initial bootstrap import of this repository (already done).
- **Small commits, one logical change per commit.**
- **Conventional Commits:** `feat:`, `fix:`, `docs:`, `test:`, `chore:`
  with an optional scope, e.g. `feat(cli): add doctor command`.
- **English only** for all files, code, comments, and commit messages.

## Pre-PR checks

Run locally before opening a PR:

```bash
shlepa smoke     # doctor + hello-file end-to-end + MLflow run
shlepa zip       # build passes, archive <= 10 MB, run.sh present
flake8 agent cli # uses the root .flake8 config
```

CI runs the same checks on every PR, plus a `shlepa smoke` against the
secondary endpoint (results go to the MLflow experiment `shlepa-ci`).

## Tasks

- Tasks live in `tasks/<source>-<slug>/` in Harbor format. Source prefixes:
  `contest-` (vendored from the competition), `<benchmark>-` (adapted from
  other benchmarks), `own-` (self-made).
- To add a task: `shlepa task new <source>-<slug>`, fill in the scaffolded
  files, update the registry table in `tasks/README.md`, commit.
- Task format, provenance rules, and benchmark adaptation: `docs/tasks.md`.
- Vendored contest tasks are synced from upstream and must stay
  byte-identical except for the provenance metadata in `task.toml`.

## CI

- **Every PR:** zip build + size check, flake8, `shlepa smoke` against the
  secondary endpoint.
- **Push to `main` touching `tasks/` or `agent/`:** full
  `shlepa submit-test --ci` run of the local task set.
- Required repository secrets (GitHub UI → Settings → Secrets):
  `CI_OPENAI_BASE_URL`, `CI_OPENAI_API_KEY`, `CI_MODEL`,
  `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`,
  `MLFLOW_TRACKING_PASSWORD`.

## Safety zones

- Never commit `.env` or any real credential.
- Never add OpenTelemetry dependencies to the agent's base dependencies —
  telemetry is an opt-in extra and is stripped from the submission zip.
- Never modify `agent/agent.py` beyond upstream sync (organizers overwrite it).
- Never break the submission contract: `run.sh` at the zip root, archive
  <= 10 MB.
