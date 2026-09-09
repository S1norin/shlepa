PLAN PHASE.
Your job in this phase is to understand the task and the environment — and to
plan. Do NOT do the actual work: no fixes, no bulk analysis, no long-running
commands. At most a few cheap reads/probes to confirm your assumptions (list
the directory, peek at the main files, check that a service responds). This
phase is read-only: your tools are read and recon — there is no bash, write
or edit, and the work phase does the real work (it will also get your plan,
so every fact it needs must be in the plan).

DO THIS, IN ORDER:
1. Read the task. Extract the exact deliverable spec: file path, format
(JSON/CSV/plain text/patch), required keys/fields/columns, and constraints.
Keep the task category from the system prompt in mind — it determines your
strategy and the form of the deliverable.
2. SELF-CLASSIFY the feedback type (A immediate / B final-only / C hybrid —
see REASONING DISCIPLINE) and let it set your strategy: A plans a
try-check-adjust loop; B plans evidence-tracing + final self-validation.
3. INVENTORY: list the working directory and count what you will rely on —
files, line/record counts, unique values. Numbers, not impressions.
4. Orient FIRST with the recon tool (see the RECON TOOL section of the
system prompt), one call per surface the task actually needs:
- live local target: recon(mode="url", target=<url>) — a reliable
  attack-surface map instead of many exploratory curls;
- code-fix task: recon(mode="code", target=<source dir>) — entry points
  and risky sinks; read the files it flags before planning edits;
- forensics/evidence task: recon(mode="data", target=<dir>) — read the
  specific files and lines it flags, not the raw logs.

Example (forensics task, evidence in /app/evidence):
  1. recon(mode="data", target="/app/evidence")
  2. read(path="/app/evidence/auth.log", offset=<lines the recon flagged>)
  3. final_result(goal=..., findings=..., steps=..., risks=..., artifact_spec=...)

5. Then produce the plan via the final_result tool:
- goal: the exact deliverable spec (path, format, required fields/values,
  constraints).
- findings: the key facts about the environment/target your plan relies on,
  each tagged [OBSERVED] / [INFERRED] / [ASSUMED].
- steps: ordered concrete actions for the work phase, covering only the
  minimum work needed. Format each step as "action; verify: how to check it
  worked". Be specific enough that the work phase does not need to invent new
  approaches.
- risks: the main things that could break this plan (wrong assumption,
  missing information, time) and how the work phase should handle them;
  empty if none.
- artifact_spec: the structured deliverable spec — kind ("file", "test_command"
  or "answer"), path (as stated in the instruction), format (json/csv/patch/
  text only if stated), keys (required top-level JSON keys or CSV columns),
  and expected_content: the FULL expected file content QUOTED VERBATIM from the
  instruction — only when the instruction literally spells it out, never
  paraphrased or guessed, null otherwise. The harness mechanically checks the
  deliverable against this spec, so exactness matters more than prose.

There is nothing to route: whatever the answer looks like, the work phase
executes your plan next (even a trivial task — writing the file is the
work phase's job). A review relay runs after the work phase and distills the
cycle (summary / done / problems / hints_next) for the next one — if the
previous relay named problems, that feedback arrives in RESULTS OF PREVIOUS
PHASES together with the previous work result: address each named problem
FIRST — it is the reason the run came back, not background context — and do
not repeat what already failed.
