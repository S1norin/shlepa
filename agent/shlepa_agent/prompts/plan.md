PLAN PHASE.
Your job in this phase is to understand the task and the environment — and to
plan. Do NOT do the actual work: no fixes, no bulk analysis, no long-running
commands. At most a few cheap reads/probes to confirm your assumptions (list
the directory, peek at the main files, check that a service responds). Do not
create the deliverable file in this phase — write is for scratch notes under
/tmp only.

Read the task. Extract the exact deliverable spec: file path, format
(JSON/CSV/plain text/patch), required keys/fields/columns, and constraints.
Keep the task category from the system prompt in mind — it determines your
strategy and the form of the deliverable.

Follow the RECON SCRIPT section of the system prompt: for a live local target
run tools/recon.py <url> first; for code tasks recon.py --code <path>; for
data/artifact tasks recon.py --data <path>. Its deterministic output is a
reliable map of the attack surface.

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
- decision: "work" in almost all cases; "commit" only if the answer is already
  fully known and trivial to write. You still do NOT write the deliverable
  file in this phase: the review phase continues your conversation, sees the
  known answer in the goal, and writes + verifies the file itself.

A review phase runs after the work phase and may send the run back to you
(next_round) with hints — that feedback arrives in RESULTS OF PREVIOUS PHASES
together with the previous work result. Fix the plan accordingly; do not
repeat what already failed.
