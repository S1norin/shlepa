⚠️ COMMIT PHASE. Stop exploring. The work is done or the budget is exhausted.
Write/verify the final deliverable NOW to the exact path in the exact format,
using only the information you already have. If the deliverable file already
exists, verify it exactly once (re-read / jq / wc -l) and correct it if
wrong. If it does not exist, create it now from what you have — a
best-effort deliverable scores better than nothing.
Use only the tools needed to write and verify the file.

Finish via the final_result tool:
- status: "ok" — the deliverable exists and ALL mechanical checks passed;
  "partial" — best-effort written, some checks failed or missing;
  "unverified" — written, but not checked.
- artifact: the absolute path of the deliverable file.
- checks: each mechanical check you ran and its outcome, one entry per check
  (e.g. "jq . /app/out.json -> valid"). Empty if nothing was checked.
- notes: one line describing the deliverable (empty if self-evident).

If the format checks pass, stop immediately — do not polish, re-verify, or
start a second pass. The deliverable file is what is scored.
