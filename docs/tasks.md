# Task format (Harbor / contest schema 1.2)

Tasks live in `tasks/<slug>/` in a flat layout. A task is **discoverable**
when its directory contains a `task.toml`; directories without one are
ignored by `shlepa run` (see `tasks/README.md` for the registry).

## Directory layout

```
tasks/<slug>/
├── task.toml            # manifest (below); makes the task discoverable
├── instruction.md       # the ONLY text the agent sees
├── environment/         # docker build context for the task env image
│   ├── Dockerfile       # FROM secureintelligent/acp:latest, WORKDIR /app
│   ├── entrypoint.sh    # optional: starts task services, then blocks
│   └── ...              # task fixtures (app sources, logs, ...)
├── tests/
│   ├── test.sh          # faithful verifier (see "Verifiers" below)
│   └── test_*.py        # optional pytest files (fallback path)
└── solution/
    └── solve.sh         # reference solution (never used by shlepa run)
```

- `environment/` is the docker build context; the image is built as
  `shlepa-task-<slug>:env`. The agent's working directory inside the
  container is `/app` (`LOCAL_AGENT_WORKDIR=/app`).
- If the task needs long-running services, start them from
  `environment/entrypoint.sh` (the image `ENTRYPOINT`) before it blocks;
  `shlepa run` then runs the container with a `sleep infinity` command.
- `solution/` is documentation: how the task is solved by hand. The dev
  engine never executes it.

## task.toml

```toml
schema_version = "1.2"

[task]
name = "own/example-task"        # display name; also used as the MLflow run name
description = "One-line summary of the task goal."
authors = []
keywords = []

[metadata]
difficulty = "easy"              # easy | medium | hard (convention, not enforced)
category = "programming"
tags = []
source = "own"                   # see "Source taxonomy" below

[verifier]
timeout_sec = 120.0              # hard timeout for the verifier step

[agent]
timeout_sec = 300.0              # hard timeout for the agent step

[environment]
build_timeout_sec = 600.0        # docker build timeout
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true            # advisory: dev runs use --network host
mcp_servers = []

[verifier.env]                   # env vars for the verifier step (test.sh)
# KEY = "value"

[environment.env]                # env vars for the agent step (inside container)
# KEY = "value"

[solution.env]                   # env vars for the reference solution (unused)
```

Fields actually consumed by `shlepa run` (see `cli/shlepa_cli/tasks.py`):

| field | used for |
|-------|----------|
| `[task] name` | display name; MLflow run name (falls back to top-level `name`, then the directory slug) |
| `[metadata] difficulty` | reported in `shlepa run --dry-run` |
| `[agent] timeout_sec` | hard timeout for the in-container agent step |
| `[verifier] timeout_sec` | hard timeout for the verifier step |
| `[environment].env` | environment of the agent step |
| `[verifier].env` | environment of the verifier step (`tests/test.sh`) |

Everything else is metadata for humans and for future tooling.

### Verifiers

The faithful contest verifier is `tests/test.sh`, executed inside the
container as `bash /tests/test.sh`. It must write the reward to
`/logs/verifier/reward.txt`: `1` (solved) or `0` (not solved). The
`/logs/verifier` directory is a host mount, so `shlepa run` reads the
file after the verifier exits.

If `tests/test.sh` is absent, `shlepa run` falls back to running the
`tests/` directory with pytest inside the container (legacy/synthetic
tasks only — prefer `test.sh` for new tasks).

## Source taxonomy

The slug is `<source>-<...>` and the first segment is the source class:

| prefix | meaning | provenance |
|--------|---------|------------|
| `contest-` | vendored from the Universal Agent Competition (SecureIntelligent) | upstream repo + `synced_at` date |
| `<bench>-` | adapted from a public benchmark (`<bench>` = benchmark slug, e.g. `bench-ctf-...`) | benchmark name + version/URL in `[metadata]` |
| `own-` | authored locally | author in `[task] authors` |

## Provenance rules

1. Every vendored/adapted task carries `[metadata]` keys
   `source`, `url`, `synced_at` (YYYY-MM-DD) in its `task.toml`,
   appended after `tags` while keeping all upstream keys intact.
2. Every task — vendored or local — appears in the registry table in
   `tasks/README.md` with slug, source, sync date, difficulty and a
   one-line description.
3. Vendored content stays byte-identical to upstream except for the
   `[metadata]` provenance keys in `task.toml`; the sync procedure in
   `tasks/README.md` includes a `diff -r` verification step.

## Adding a task

```bash
# 1. scaffold (source prefixes: contest | bench | own)
shlepa task new own-my-task

# 2. fill in:
#    tasks/own-my-task/instruction.md   (agent-visible goal)
#    tasks/own-my-task/task.toml        ([task], [metadata], timeouts)
#    tasks/own-my-task/environment/     (Dockerfile FROM acp, fixtures, entrypoint)
#    tasks/own-my-task/tests/test.sh    (writes /logs/verifier/reward.txt)
#    tasks/own-my-task/solution/solve.sh (reference solution)

# 3. add a registry row to tasks/README.md

# 4. sanity check, then commit
shlepa run --dry-run all          # must list the new task
shlepa run my-preset              # or a preset containing it
git add tasks tasks/README.md
git commit -m "feat(tasks): add own-my-task"
```

Commit messages follow Conventional Commits; use `feat(tasks)` for new
tasks, `chore(tasks)` for syncs, `fix(tasks)` for corrections.

## Adapting an external benchmark

To turn a benchmark item into a Harbor-format task:

1. **Pick the slug**: `<bench>-<item-slug>` (lowercase, hyphenated).
2. **Copy the material** into `tasks/<slug>/environment/` and write a
   `Dockerfile` based on `secureintelligent/acp:latest` (the agent
   runtime). Copy fixtures with `COPY` into `/app`; put service startup
   into `entrypoint.sh` if needed.
3. **Write `instruction.md`** — the full agent-visible statement. The
   agent sees only this text plus its `/app` working directory.
4. **Port the checker** to `tests/test.sh`: it runs as root in the
   container with `/tests` mounted read-only and must write `1`/`0` to
   `/logs/verifier/reward.txt`. Benchmark checkers that need the network
   must be re-scoped to the container (dev runs are `--network host` but
   submissions run sandboxed — keep checkers self-contained).
5. **Save the reference solution** in `solution/solve.sh` (and test it
   once by hand in a container).
6. **Record provenance** in `[metadata]`: `source` (benchmark repo or
   name), `url` (item URL), `synced_at`.
7. Register it in `tasks/README.md`, then `shlepa run --dry-run` + one
   real run to verify the verifier path end to end.
