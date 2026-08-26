---
name: backlog
description: Convert research notes (research/notes/*.md) into GitHub backlog issues. Use when the user says "add to backlog", "turn this note into issues", "file issues from the research notes", or after a new research note lands. Dedupes against existing issues and applies the repo label conventions (see the github-issues skill for the full lifecycle).
---

# Research notes → GitHub backlog issues

Turn findings in `research/notes/*.md` into concrete GitHub issues so
the backlog (GitHub issues, per AGENTS.md) reflects the research.

## Workflow

1. **Pick the source note(s)**: `ls research/notes/` and read the
   note(s) the user pointed at (or all unread ones if unspecified).

2. **Extract candidate asks.** A valid backlog item is a *concrete,
   verifiable action for the repo* — not a research observation.
   Typical forms:
   - "Adapt benchmark X task Y into `tasks/bench-<slug>` (see
     `docs/tasks.md` adaptation steps)"
   - "Try technique Z from <paper> in the agent prompt/loop"
   - "Support <feature> in `cli/shlepa_cli/…`"
   Pure observations ("LLMs do better with fewer tools") are not
   issues; if actionable, phrase the action ("Test the agent with a
   single-file workspace on the sqli tasks").

3. **Dedupe** (MANDATORY, before creating anything):

   ```bash
   gh issue list --state open --limit 200 --json number,title,labels
   gh search issues --repo S1norin/shlepa "<2-3 keywords>" --limit 20
   ```

   Skip candidates already covered by an open issue; note the skipped
   ones in the summary to the user.

4. **Create issues** (one per ask, English):

   ```bash
   gh issue create \
     --title "<concrete ask, <=70 chars>" \
     --body "$(cat <<'EOF'
   ## Context
   From research note `research/notes/<file>.md` (<section heading>):
   <1-2 sentence why this matters for the agent/competition>

   ## Ask
   <the single concrete deliverable>

   ## Acceptance
   - [ ] <observable check>

   ## Source
   - Note: `research/notes/<file>.md#<section>`
   - Paper/link: <url if any>
   EOF
   )" \
     --label "backlog" --label "source:research" --label "area:<area>"
   ```

   Label rules (see `github-issues` skill): exactly one `area:*`
   (`agent|tasks|telemetry|ci`), `priority:*` only if the user set one.

5. **Report** to the user: created issue numbers + titles, skipped
   candidates with the duplicate they matched.

## Rules

- Every issue body cites the note path and section (so the trail is
  auditable) — no long pastes of note content.
- One ask per issue. A note section with three independent actions →
  three issues (they will usually share the same `area:*`).
- Do not edit the research note when filing (notes are append-only
  sources of truth); the issue is the tracking unit.
- If `gh` is not authenticated, stop and tell the user
  (`gh auth status`).
