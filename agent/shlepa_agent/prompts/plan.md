PLAN PHASE.
Your job in this phase is to understand the task and the environment — and to
plan. Do NOT do the actual work: no fixes, no bulk analysis, no long-running
commands. At most a few cheap reads/probes to confirm your assumptions (list
the directory, peek at the main files, check that a service responds). This
phase is read-only: your tools are read, recon and search — there is no
bash, write or edit, and the work phase does the real work (it will also
get your plan, so every fact it needs must be in the plan).

Read the task. Extract the exact deliverable spec: file path, format
(JSON/CSV/plain text/patch), required keys/fields/columns, and constraints.
Keep the task category from the system prompt in mind — it determines your
strategy and the form of the deliverable.

Follow the RECON TOOL section of the system prompt: for a live local target
call recon(mode="url", target=<url>) first; for code tasks
recon(mode="code", target=<path>); for data/artifact tasks
recon(mode="data", target=<path>). Its deterministic output is a reliable
map of the attack surface; use search for targeted greps and file listings
when recon is not enough.

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

There is nothing to route: whatever the answer looks like, the work phase
executes your plan next (even a trivial task — writing the file is the
work phase's job), and a review phase runs after the work phase and may
send the run back to you (next_round) with hints — that feedback arrives
in RESULTS OF PREVIOUS PHASES
together with the previous work result. Fix the plan accordingly; do not
repeat what already failed.
