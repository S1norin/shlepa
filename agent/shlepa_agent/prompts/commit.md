⚠️ REVIEW PHASE. The run ends after this phase unless you decide
'next_round' — every 'next_round' starts a new plan/work cycle.

1. Verify the deliverable MECHANICALLY against the task spec: re-read the
   file at the exact path, validate the format (jq / python -c json.load /
   wc -l), compare every required name, value, and order. Do not trust the
   previous phase's word — check the file itself.
2. If it is missing or broken: fix it NOW. You have full tools
   (read/write/edit/bash) — repair the file, write it best-effort if it
   does not exist. A partial deliverable scores better than nothing.
3. Decide:
   - status: "ok" — the deliverable exists and ALL mechanical checks
     passed; "partial" — something is missing, broken or unchecked.
   - verdict: "done" — stop with the current deliverable (best effort if
     partial); "next_round" — only if a new plan/work round would
     MATERIALLY improve the result (you must be able to say what exactly
     was wrong). Never choose "next_round" for polish.
   - hints: for "next_round" only — concrete instructions for the next
     plan (what was wrong, what must change); empty list for "done".
   - artifact: the absolute path of the deliverable file (empty if none).
   - checks: each mechanical check you ran and its outcome, one entry per
     check (e.g. "jq . /app/out.json -> valid"). Empty if nothing was
     checked.
   - notes: one line describing the deliverable (empty if self-evident).

Finish via the final_result tool. After the checks pass, stop immediately —
do not polish, re-verify, or start a second pass. The deliverable file is
what is scored.
