PLAN PHASE.
Your job in this phase is to understand the task and the environment — and to
plan. Do NOT do the actual work: no fixes, no bulk analysis, no long-running
commands. At most a few cheap reads/probes to confirm your assumptions (list
the directory, peek at the main files, check that a service responds). This
phase is read-only: your tools are read, recon, search, code_search,
file_outline and log_triage — there is no bash, write or edit, and the work
phase does the real work (it will also get your plan, so every fact it needs
must be in the plan).

Read the task. Extract the exact deliverable spec: file path, format
(JSON/CSV/plain text/patch), required keys/fields/columns, and constraints.
Keep the task category from the system prompt in mind — it determines your
strategy and the form of the deliverable.

Orient FIRST with the tools from the ORIENTATION TOOLS section of the
system prompt, one call per surface the task actually needs:
- live local target: recon(mode="url", target=<url>) — a reliable
  attack-surface map instead of many exploratory curls;
- code-fix task: recon(mode="code", target=<source dir>); for a source tree
  bigger than ~10 files, locate the relevant file or symbol with code_search
  (a keyword or natural-language query) BEFORE reading it;
- forensics/evidence task: recon(mode="data", target=<dir>), then
  log_triage(path=<evidence dir>) — and read only the specific files and
  lines they flag, not the raw logs.
search (grep/glob/ls) fills the gaps for exact text and file names.

Example (forensics task, evidence in /app/evidence):
  1. recon(mode="data", target="/app/evidence")
  2. log_triage(path="/app/evidence")
  3. read(path="/app/evidence/auth.log", offset=<lines the triage flagged>)
  4. final_result(goal=..., findings=..., steps=..., risks=..., artifact_spec=...)

Then produce the plan via the final_result tool:
- goal: the exact deliverable spec (path, format, required fields/values,
  constraints).
- findings: the key facts about the environment/target your plan relies on.
- steps: ordered concrete actions for the work phase, covering only the
  minimum work needed. Format each step as "action; verify: how to check it
  worked". Be specific enough that the work phase does not need to invent new
  approaches.
- risks: the main things that could break this plan (wrong assumption, missing
  information) and how the work phase should handle them; empty if none.
- artifact_spec: the structured deliverable spec — kind ("file", "test_command"
  or "answer"), path (as stated in the instruction), format (json/csv/patch/
  text only if stated), keys (required top-level JSON keys or CSV columns),
  and expected_content: the FULL expected file content QUOTED VERBATIM from the
  instruction — only when the instruction literally spells it out, never
  paraphrased or guessed, null otherwise. The harness mechanically checks the
  deliverable against this spec, so exactness matters more than prose.

There is nothing to route: whatever the answer looks like, the work phase
executes your plan next (even a trivial task — writing the file is the
work phase's job), and a review phase runs after the work phase and may
send the run back to you (next_round) with hints — that feedback arrives
in RESULTS OF PREVIOUS PHASES
together with the previous work result. If the previous review named
failed checks, address each named failure FIRST — they are the reason the
run came back, not background context — and do not repeat what already
failed.
