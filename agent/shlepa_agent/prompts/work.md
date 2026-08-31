WORK PHASE.
Execute the plan from RESULTS OF PREVIOUS PHASES. Do not invent new
approaches and do not restart exploration from scratch — the plan phase
already did the understanding. Follow the plan steps in order.

Rules:
- If a step fails twice, adapt within the plan's scope with the smallest
  change; never switch strategy wholesale.
- Write the deliverable to the exact path in the exact format.
- FRESHNESS: after each significant step, update the deliverable file with
  the current best result — never finish the phase with an empty or
  stale file. A partial deliverable on disk beats a perfect one only in
  your head.
- Self-review before finishing: re-read the deliverable, validate the format
  mechanically (jq / python -c json.load / wc -l), compare names, values, and
  order against the spec. Fix any mismatch.

You do NOT decide when the run ends: a review phase always follows this one.
It verifies the file and decides done vs next_round. Your job is to leave
the best possible deliverable on disk.

Finish via the final_result tool:
- summary: what was done and how it was verified.
- deliverable: the path of the file written (empty if nothing was written).
- findings: new facts not known at planning time (empty if none).
- confidence: how sure you are (0-1) that the deliverable is complete and
  correct. Be honest: 1.0 only after a passing mechanical check.
