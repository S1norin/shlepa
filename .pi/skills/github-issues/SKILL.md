---
name: github-issues
description: Manage the Shlepa backlog as GitHub issues via the gh CLI. Use when creating, triaging, updating, or closing repo issues; when the user mentions "issue", "backlog item", "ticket", or asks to track work. Enforces the repo label conventions and English-only issue text.
---

# GitHub issues (Shlepa backlog)

The repo backlog lives in GitHub issues (`S1norin/shlepa`), not in files.
All issue content is in English. Use the `gh` CLI (authenticated, verified
by `shlepa doctor`-level tooling checks or just `gh auth status`).

## Label conventions

| label | meaning |
|-------|---------|
| `backlog` | accepted, not scheduled yet (default for new issues) |
| `area:agent` | changes under `agent/` |
| `area:tasks` | changes under `tasks/` (task format, vendoring, adaptation) |
| `area:telemetry` | OTel/Jaeger/MLflow-OTel path |
| `area:ci` | workflows, secrets, CI endpoints |
| `source:research` | came from `research/notes/` (see the `backlog` skill) |
| `priority:p1` … `priority:p3` | p1 = blocks competition, p2 = important, p3 = nice-to-have |

Rules:

- Exactly one `area:*` label per issue (pick the dominant area).
- `priority:*` only when the user explicitly set a priority — never
  invent one.
- New issues start with `backlog` + `area:*` (+ `source:research` if
  research-derived). Remove `backlog` when work is actively planned.
- Verify labels exist before use; create missing ones with
  `gh label create "<label>" --force --description "<one line>"`.

## Issue lifecycle

**Create** (always `--repo S1norin/shlepa` or run from the repo root):

```bash
gh issue create \
  --title "<imperative, <=70 chars, English>" \
  --body "$(cat <<'EOF'
## Context
<why this matters; link the note/doc/task that motivated it>

## Ask
<one concrete, verifiable deliverable>

## Acceptance
- [ ] <observable check>
EOF
)" \
  --label "backlog" --label "area:agent"
```

Body rules: Context (1–3 sentences + link), Ask (one concrete
deliverable), Acceptance (checkable bullets). Cite file paths
(`agent/shlepa_agent/core.py`, `tasks/contest-*/task.toml`,
`research/notes/<file>.md#section`) instead of pasting long excerpts.

**Triage** (review new issues):

```bash
gh issue list --state open --label backlog --limit 50
gh issue view <n> --comments
```

For each issue: confirm exactly one `area:*` label; if the ask is not
concrete, comment asking for a specific deliverable (English); close
duplicates with `gh issue close <n> --comment "Duplicate of #<m>: <why>"`.

**Close**: only when done (commit/PR link in the closing comment) or as
duplicate/invalid. `gh issue close <n> --comment "<what happened, links>"`.

## Dedupe before creating

```bash
gh issue list --state open --limit 100 --json number,title,labels
gh search issues --repo S1norin/shlepa "<keyword>" --limit 20
```

If an open issue already covers the ask, do not create a new one —
extend or reference the existing one.
