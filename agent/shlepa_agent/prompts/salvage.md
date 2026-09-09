SALVAGE PHASE.
The deliverable file is missing or empty on disk after the work phase,
and this is the last cheap chance to put it there. Your ONLY job is to
get the deliverable content onto disk.

Rules:
- You have the write tool only. No bash, no read, no edit.
- Write the deliverable file (the path is in the DELIVERABLE SPEC above).
  If you have not finished computing the answer, write the best complete
  answer you can state right now — the harness and the review phase check
  it mechanically afterwards.
- ALWAYS also fill final_result.body with the COMPLETE exact content of
  the deliverable (the same bytes you wrote). The harness persists that
  text to the path as a fallback if the file is still missing or empty
  after this phase — so fill it even when you wrote the file yourself.
- final_result.path: the deliverable path you wrote (empty if you did not
  write it).

Do not analyze, do not explore, do not re-derive from scratch beyond what
the RECOVERABLE TEXT block gives you. Write, then final_result.
