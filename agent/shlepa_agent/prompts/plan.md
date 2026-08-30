PLAN PHASE.
Your job in this phase is to understand the task and the environment — and to
plan. Do NOT do the actual work: no fixes, no bulk analysis, no long-running
commands. At most a few cheap reads/probes to confirm your assumptions (list
the directory, peek at the main files, check that a service responds).

Follow the RECON SCRIPT section of the system prompt: for a live local target
run tools/recon.py <url> first; for code tasks recon.py --code <path>; for
data/artifact tasks recon.py --data <path>. Its deterministic output is a
reliable map of the attack surface.

Then produce the plan via the final_result tool:
- goal: the exact deliverable spec (path, format, required fields/values,
  constraints).
- findings: the key facts about the environment/target your plan relies on.
- steps: ordered concrete actions for the work phase. Be specific enough that
  the work phase does not need to invent new approaches.
- decision: "work" in almost all cases; "commit" only if the answer is already
  fully known and trivial to write.

If a previous work attempt failed, its result is in RESULTS OF PREVIOUS
PHASES — fix the plan accordingly; do not repeat what already failed.
