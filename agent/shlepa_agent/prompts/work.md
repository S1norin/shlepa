WORK PHASE.
Execute the plan from RESULTS OF PREVIOUS PHASES. Do not invent new
approaches and do not restart exploration from scratch — the plan phase
already did the understanding. Follow the plan steps in order.

Rules:
- If a step fails twice, adapt within the plan's scope with the smallest
  change; never switch strategy wholesale.
- Write the deliverable to the exact path in the exact format.
- Self-review before finishing: re-read the deliverable, validate the format
  mechanically (jq / python -c json.load / wc -l), compare names, values, and
  order against the spec. Fix any mismatch.

Finish via the final_result tool:
- decision="commit" — the deliverable is ready and verified (or you have the
  best possible result with what remains of the budget).
- decision="replan" — only if the PLAN ITSELF was wrong or incomplete (wrong
  target, wrong format, missing information you cannot recover). Explain what
  was wrong in summary.
- confidence: how sure you are (0-1) that the deliverable is complete and
  correct. Be honest: 1.0 only after a passing mechanical check.
- next_hints: for decision="replan" only — concrete hints for the next plan
  (what was wrong, what must change); empty list for "commit".
- summary: what was done and how it was verified; deliverable: the path of
  the file written; findings: new facts not known at planning time.
