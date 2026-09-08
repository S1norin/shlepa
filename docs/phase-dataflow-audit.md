# Phase prompt / dataflow audit (v5 pipeline)

Date: 2026-09-07
Scope: the `plan -> work -> review` cycle as implemented in
`agent/shlepa_agent/` (v5: no task time limit, no cycle cap). Goal: find
data that crosses phase boundaries and contradicts the prompts the phases
are given, or prompt/config pairs that are internally inconsistent.

## Message assembly (context)

- **System message** (per phase, `template.py` + `config.toml [template]`):
  `base.md` (system block) + `AVAILABLE TOOLS` (per-phase tool notes) +
  `TASK` (constant for the whole run).
- **User message** (per phase), block order:
  1. `ADDITIONAL CONTEXT` — hard/soft limits (`phases/base.py limits_note`).
  2. `RESULTS OF PREVIOUS PHASES` — work: the plan's JSON dump (+ previous
     work on replan); plan (replan only): previous work JSON + review hints.
  3. `PHASE INSTRUCTIONS` — `prompts/{plan,work,commit}.md`.
  4. `OUTPUT FORMAT` — JSON schema of the phase's typed output
     (`outputs.py output_schema_note`).
- **History**: plan and work runs are always fresh. The review (commit)
  phase resumes the work conversation (`trim_history` in
  `phases/commit.py:26`); a phase hard-timeout injects one toolless
  `final_ask` request into the same conversation before routing to review
  (`runner.py:353`, `FINAL_ASK_MESSAGE` at `runner.py:77`).

## A. Hard contradictions (the model can actually be confused)

### A1. Plan timeout -> work is told to execute a plan that does not exist

`WorkPhase.prompt` (`phases/work.py:28-30`) fills the
`RESULTS OF PREVIOUS PHASES` block only when `plan.output is not None`.
When the plan phase hits its 60 s cap, `state.results["plan"]` is a
timeout result with `output=None`, so the block is dropped entirely. The
work user message then contains only:

> "Execute the plan from RESULTS OF PREVIOUS PHASES in order. Do not invent
> new approaches and do not restart exploration from scratch"

— a reference to a nonexistent plan plus a ban on improvising. The
plan's `final_ask` reply (one free-text line) lives in the plan
conversation, which is never resumed by work.

Fix direction: when the plan produced no typed result, either drop the
"execute the plan in order / do not invent" wording (fall back to a
"no plan was produced; derive the minimum work yourself" instruction) or
include the plan's `final_ask` free text in the work prompt.

### A2. Work timeout -> the review transcript contains a stale instruction

After the 120 s work cap, the runner sends `FINAL_ASK_MESSAGE`
(`runner.py:77-85`) into the same conversation: "HARD TIME LIMIT
REACHED ... reply with one short line naming its path ... Do not call any
tools and **do not think any further**." The model's free-text reply is
appended, and the review then resumes this exact history.

Two problems:

1. `commit.md` step 1 says "Work must have reported a file path in its
   **deliverable field**" and "timed out without a file ... verdict MUST
   be next_round". After a timeout there is no `WorkResult` at all — only
   the `final_ask` line. The prompt does not say what to do in the case
   "timed out, but the final_ask line names a file that is on disk and
   largely complete". The verdict is left to model interpretation.
2. The stale imperative "do not think any further" sits in the same
   conversation immediately before the review's own instructions, which
   require judging.

Fix direction: add an explicit review rule for "work timed out but a
path is named in the transcript" (e.g. treat the line as the deliverable
report, judge completeness from it), and/or mark the `final_ask` exchange
as history rather than a standing instruction.

### A3. `work.md` FRESHNESS vs the write tool's no-overwrite contract

`work.md` says: "after each significant step, **update** the deliverable
file" and "Prefer read/write/edit over bash for any file operation". The
`write` tool never overwrites (`tools/write.py:35-36`:
"File already exists (use edit to change it)"). So every update after the
first is either an `edit` (exact `oldText` needed; file content only
known through 4000-char `read` pages) or `bash` — which the prompt
reserves "for commands, servers, and checks that file tools cannot do".
The prompt systematically funnels the model into a guaranteed tool error
on every second update of the deliverable.

Fix direction: state it explicitly in `work.md`: "update = `edit` or a
bash write; `write` is first creation only".

### A4. (minor) Two conflicting AVAILABLE TOOLS narratives in the review

The review resumes the work conversation whose first system message lists
7 tools (+ the recon prompt block), while the review's fresh system
message and user instructions say NO TOOLS. Intentional design, but the
stale 7-tool block is noise the model has to discount; `base.md`'s
ROLE AND PHASES section already covers per-phase tooling.

## B. Logical inconsistencies (do not break, but do not add up)

### B1. The terminal judge runs with `reasoning_effort = "low"`

`config.toml:129` (`[phases.commit]`) is the only phase with an explicit
reasoning effort — and the lowest one. The done/next_round verdict plus
the hints that steer the next cycle are the most consequential decision
in the loop, while plan/work run on the endpoint default. If the default
is higher than `low`, the design deliberately makes the judge the least
reasoning phase.

### B2. `PlanResult.decision` is a dead field and a trap

`outputs.py:49`: the schema allows `"commit"`, the field description
admits it is legacy, `plan.md` says the value is always `"work"`, and the
runner routes plan -> work unconditionally (`runner.py` pipeline walk).
The model can emit `"commit"` and nothing will tell it that was invalid.

### B3. `WorkResult.confidence` has no consumer

`outputs.py:77`. The prompt demands calibration discipline ("1.0 only
after a passing mechanical check"), the runner never reads the field, and
the review has no rule to use it (it is visible in the transcript as part
of the `final_result` call, but nothing says to weigh it).

### B4. The review has neither time nor disk information

`commit.md` says "no time or cycle cap", while the container is killed at
the task's own limit. The review cannot weigh whether another full cycle
(plan 60 s + work 120 s + review 45 s) fits before the kill, so it can
commit the container's last seconds to a cycle that times out with no net
gain. Structurally by design ("whatever is on disk at kill time scores"),
but a blind spot worth knowing.

### B5. `next_round` with empty hints is legal and unhandled

`ReviewResult.hints` defaults to `[]` and `commit.md` does not mandate
non-empty hints for `next_round`. The plan prompt renders the hints block
only `if hints` (`phases/plan.py:42-46`), so a hint-less `next_round`
hands the next plan only the previous work JSON and no directive.

### B6. Context-overflow cascade

`UsageLimitExceeded` is treated as a timeout (`runner.py:119-133`):
final_ask fires on the same overflowing conversation (likely fails, error
logged only), then the review runs on the same overflowing history with
`max_retries=0` — its first request can also fail, and the run ends
`status="error"` even when a good deliverable is on disk. The
`FINAL_ASK_MESSAGE` text ("HARD TIME LIMIT REACHED") is also wrong for
this case: the breach is a context limit, not a time limit.

### B7. Stale/incoherent tuning knobs in `config.toml`

- `[phases.*].requests` (25/100/20, lines 101/115/126/136) are unused:
  v5 removed request-count limits and the runner never reads them.
- `soft_tokens`: plan = 15000 ("keep the output lean"), review = 20000
  for a small structured JSON, work has none. The three values do not
  form a consistent scheme (advisory only, not model-breaking).

### B8. `base.md` scoping (minor)

System-prompt lines aimed at other phases: "Start any server with nohup,
&, then verify it responds" and "Run scripts with /app/.venv/bin/python"
apply to plan too, where bash does not exist (`plan.md` overrides, being
more specific — not contradictory, but it creates temptation/confusion in
the only phase without bash). Similarly, `base.md` names only
read/bash as UNTRUSTED-wrapped tools, while recon and code_search are
wrapped too (`tools/base.py:113`, `tools/recon.py:97`,
`tools/code_search.py:62`) — a documentation gap, not a security gap.

## C. Checked, no problem

- **The review does see the `WorkResult`.** pydantic-ai appends a
  `ModelRequest` with the `final_result` `ToolReturnPart` to the message
  history when the output tool fires (`_handle_final_result` in
  `pydantic_ai/_agent_graph.py`), and `trim_history`
  (`phases/commit.py:26-43`) keeps it (it only drops a trailing
  tool-less user request and trailing unpaired tool calls). So
  "Work must have reported a file path in its deliverable field" has its
  data in the transcript in the clean-completion case.
- **Replan data is fresh.** `state.results` is overwritten on every
  attempt (`runner.py _run_phase_with_retries`); the Nth plan gets the
  latest previous work JSON + latest review hints, the Nth work gets the
  current plan JSON + the immediately previous work JSON. No stale
  entries accumulate.
- **UNTRUSTED wrapping** covers all environment-data tools
  (read, bash, recon, code_search, log_triage).
- **`final_ask` does not mutate `state.results`** — no phantom phase
  data reaches the next phases.
- **Review "done" with `status="partial"`** is coherent: the run stops
  with the best-effort deliverable, as documented.

## Suggested follow-ups

1. Fix A1 (plan-less work prompt) — highest real-world impact.
2. Fix A2 (review rule for timeout-with-path) and clarify A3 in `work.md`.
3. Decide B1 deliberately (review reasoning effort).
4. Sweep B2/B3/B5/B7 in one config/prompt consistency pass.
5. B4/B6: document or special-case (context-overflow final_ask/review).

## Resolution (implemented on `feature/phase-dataflow-fixes`, 2026-09-08)

Design constraint: the `plan -> work -> review` pipeline is unchanged;
only the identified problem spots were touched. Dead code was marked,
not deleted.

- **Review is now read-only verification** (resolves A4, B1, B4 in part,
  and enables A2-style judging): `[phases.commit].tools =
  ["read", "code_search", "file_outline"]` in `config.toml`; the review
  re-checks the deliverable and key claims on disk instead of judging
  from the transcript alone. No bash, no writes, no recon (per-call cost
  is too high for a 60 s cap). `commit.md` rewritten as a verification
  judge (verify existence -> re-verify claims -> contradiction check ->
  verdict), with a ~5 read/search-call budget. `runner.py _system_prompt`
  renders no recon prompt block for a phase that has neither `recon` nor
  `bash` (previously the work-conversation resume would have leaked the
  bash-based recon block into the toolless review). Config arms never
  augment the review: `_append_to_phases` and `_apply_read_only_arm`
  skip the `commit` phase id, so `+recon`/`+forensics`/`+mitre-kb` /
  `read-only` cannot add tools to it.
- **B1**: the explicit `reasoning_effort = "low"` was removed from
  `[phases.commit]` — the judge now runs on the endpoint default, the
  same regime as plan/work.
- **Caps**: plan 60 -> 80 s (`budget.py PLAN_CAP`, `soft_time` 45 -> 60),
  review 45 -> 60 s (`REVIEW_CAP`, `soft_time` 35 -> 45) — the review
  now does real disk verification and is terminal (no retry), so the
  cap must fit several read/search round trips. Full cycle 225 -> 260 s.
- **A1**: `work.py` renders an explicit fallback when the plan produced
  no typed result: "No plan was produced ... derive the minimum work
  yourself" replaces the "execute the plan ... do not invent" wording.
  Refined in the same branch: a plan timeout no longer skips straight to
  the review — the one-shot `final_ask` now asks the plan to leave its
  plan as plain text (goal/findings/steps/risks), the reply is stored on
  `PhaseResult.note`, and the pipeline continues with **work** executing
  that salvaged plan (work flags it as possibly incomplete); the
  derive-from-task fallback stays for a final_ask that produced nothing.
- **A2 / B6**: `FINAL_ASK_MESSAGE` split into reason-specific heads
  (`_final_ask(..., reason="time" | "context")`): the time variant keeps
  the "hard time limit" framing, the context variant says the context
  window is exhausted (no more history will fit) instead of a wrong time
  claim; both now tell the model the review will re-check the disk.
  `commit.md` step 1 explicitly covers "work timed out but a path is
  named in the transcript": treat the line as the deliverable report,
  verify it with read, judge from disk.
- **A3**: `work.md` FRESHNESS now states `write` is first creation only;
  updates go through `edit` or a bash write.
- **B2**: `PlanResult.decision` marked DEAD (legacy, ignored by the
  runner; kept for output-schema stability) with a "always emit work"
  instruction in `plan.md`/schema description.
- **B3**: `WorkResult.confidence` marked as having no downstream
  consumer (kept in the schema for stability).
- **B5**: `commit.md` mandates non-empty `hints` for `next_round`; `plan.py`
  now renders the review-context block even for a hint-less `next_round`,
  with a fallback directive (re-read the previous work, target the
  weakest/unchecked claims).
- **B7**: `requests` in `[phases.*]` marked unused in `config.toml` (the
  values are kept, never read by the v5 runner); the `soft_tokens`
  scheme left as-is (advisory only).
- **B8**: `base.md` server-start line scoped to the work phase; the
  UNTRUSTED tool list now names all wrapped tools (read, bash, recon,
  code_search, file_outline, log_triage).
- **B4**: left as documented by design (the container kill is opaque to
  the agent); the review's disk re-check mitigates the "commit the last
  seconds to a doomed cycle" risk only partially — no change made.
- Tests updated to the new semantics (budget caps, commit tool set,
  arm augmentation skipping commit, final-ask messages, host-mode stub
  flow plan+work+commit) and the golden fixture
  `agent/tests/fixtures/default_prompt.txt` re-captured.
