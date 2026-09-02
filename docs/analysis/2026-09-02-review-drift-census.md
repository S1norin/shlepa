# REVIEW drift census — offline replay on 474 traces (2026-09-02)

Companion data pack for [`agent-v6-review-redesign.md`](../plans/agent-v6-review-redesign.md)
(phase R1 gate). All numbers below are deterministic replays of exported OTel traces;
no LLM judge is involved.

## 1. Data

- **474 agent traces**, exported from the `shlepa-traces` MLflow experiment
  (id 21) via a paged search (see §6, finding F7).
- **14 batches**, window 2026-08-31 09:04 → 2026-09-01 13:02 UTC:
  12 batches on `Qwen3.6-35B-A3B` (34 tasks each, last batch 30) and
  2 batches on `Qwen3.8-27B-UD-IQ4_XS` (35/32 tasks).
- **Correlation with results: 474/474 (100%)** — every trace was matched to an
  MLflow run by `(batch_id, run_name)` (per-run inventory in
  `tmp/analysis/mlflow_inventory.json`, regenerated 2026-09-02).
- Exports: `tmp/trace-export/<batch>/` (traces + digests + manifest).
- Census script: `tmp/analysis/review_census.py`; rows:
  `tmp/analysis/review_census/review_census.jsonl`.

Phase attribution uses the `PLAN PHASE.` / `WORK PHASE.` / `REVIEW PHASE`
markers inside the user messages of each `invoke_agent` span
(commit spans embed the full history, so priority is commit > work > plan).
"Commit capped" = the commit-phase span ran ≥ 44 s (proxy for hitting the
45 s `REVIEW_CAP` and being aborted, since a clean finish always emits a
`final_result` and a capped one does not — the 138 traces without a parsed
`ReviewResult` coincide with 96% of the capped cohort).

## 2. Headline numbers

| Cohort | n | solved | rate |
|---|---|---|---|
| All, 35B | 406 | 202 | **49.8%** |
| All, 27B | 67 | 28 | **41.8%** |
| **Commit-capped (REVIEW aborted)** | **144** | **32** | **22.2%** |
| Commit clean (REVIEW emitted verdict) | 330 | 198 | 59.7% (35B) / 64.5% (27B) |

**A trace whose final REVIEW phase was aborted by the 45 s cap solves at
22.2% — 2.7× (35B) to 3.4× (27B) worse than a trace whose REVIEW finished.
One-third of the corpus (144/474 = 30.4%) died in the cap.** That single
cohort is the entire addressable surface of the redesign.

## 3. What the capped cohort was doing in REVIEW (H1)

144 capped traces, commit-phase tool behavior:

| Commit behavior in the 45 s | n | solved | rate |
|---|---|---|---|
| ≥1 write/edit call (repair, or artifact churn) | 54 | 16 | 29.6% |
| ≥3 exploratory calls (grep/find/cat on non-artifact paths) | 33 | 10 | 30.3% |
| verify-like calls only (read/grep of the artifact) | 5 | 2 | 40.0% |
| other / idle (no tool calls or <3 exploratory, no writes) | 52 | 4 | 7.7% |

- 109/144 (75.7%) of capped traces made **at least one tool call** in REVIEW —
  the phase was not sitting idle, it was *working*.
- 48/144 (33.3%) show the pure drift pattern (≥3 exploratory calls, no writes):
  fresh analysis during a phase that should only verify and terminate.
- 54/144 (37.5%) **wrote files inside the 45 s cap** — repair is happening in
  the terminal phase and then gets aborted before `final_result`.

**H1 (drift is measurable): CONFIRMED** at material prevalence (76% of capped
had tool activity; 33% pure exploratory drift).

## 4. `final_ask` and salvage (H2, H3)

- The tool-less `final_ask` exchange (WORK/PLAN timeout → `HARD TIME LIMIT
  REACHED` user message, then a tool-less answer) is visible in the commit
  history of **183/474 (38.6%)** of traces — it is a common path, not an edge.
- Of the 144 capped traces, 124 (86%) had `final_ask` in history: the pipeline
  already announced "time is up", and then REVIEW still burned its full 45 s on
  work.
- **Salvage quality (H3): the expected lever is weak.** Only **7/183 (3.8%)**
  of `final_ask` answers mention a path/answer-like token (`/app`, `/tmp`,
  `*.py`, …). The model's last tool-less monologue rarely contains the
  deliverable. Harness-persisting that body is therefore **not** a meaningful
  score-recovery channel.
- **H2 (artifact was already fine):** partially supported. 54 capped traces
  wrote during REVIEW, which implies the artifact existed (or was being
  (re)produced) inside the cap; a strict test needs workspace file timestamps
  (out of scope for this census) — marked **PARTIAL / deferred**.
- **H4 (the loop is mostly one cycle): CONFIRMED.** `next_round` verdicts:
  **1/474 (0.2%)**. 335 traces ended with a `done` verdict, 138 emitted no
  verdict at all (the capped set). The review→new-cycle escape hatch is dead
  weight; nothing in the redesign needs to preserve it for the clean path.

## 5. Verdicts for the plan gate

| Gate | Result |
|---|---|
| H1 material drift | **CONFIRMED** — proceed with R2 (commit barrier) and R3 (VERIFY/REPAIR split) |
| H2 artifact-was-fine | **PARTIAL** — do not gate on it; verify via workspace mtimes in R5 experiments |
| H3 salvage text | **REJECTED as score lever** — deprioritize harness-persist of `final_ask` body (keep it only as a context input for the split VERIFY) |
| H4 loop rarity | **CONFIRMED** — safe to drop `next_round` recovery from the redesign |

## 6. Incidental finding (F7) — CLI export bug

`shlepa trace-export` (`find_batch_traces` in
`cli/shlepa_cli/trace_export.py`) searches the trace experiment with a single
**non-paginated** `search_traces(max_results=500)`. The experiment now holds
**742** traces, so any batch whose traces fall outside that page silently
returns "no agent traces found". Tonight all 14 target batches reported
"not found" until the export was redone with a paged scan
(`tmp/analysis/export_paged.py`), which recovered **all 468** of their traces.

- Impact: the trace-export workflow is unreliable exactly when the experiment
  grows past 500 traces — i.e. right now, by default.
- Fix (backlog, not this analysis): paginate `find_batch_traces`
  (`page_token` loop) and/or filter by the batch's time window
  (`request_time`) before the span-level batch-id match.

## 7. Limitations

- 2 models, one 34-task sweep (looped 12× for 35B): task mix is fixed, so
  per-family drift rates (SOC-detection wall) are not broken down here.
- "Commit capped" is a 44 s proxy + missing-`final_result` check, not a
  harness signal (the F4 telemetry gap); a handful of genuinely long-but-clean
  commits could be miscounted.
- Exploratory/verify classification is path-based (artifact = first
  write/edit path in the trace); tasks with multiple artifacts under-report
  exploratory drift, so 33% is a lower bound.

## 8. Reproduce

```bash
# one-off export (server-side, paged — workaround for F7)
uv run --project cli --no-sync python tmp/analysis/export_paged.py
# census
uv run --project cli --no-sync python tmp/analysis/review_census.py tmp/trace-export/*/
# solved correlation (uses tmp/analysis/mlflow_inventory.json)
# (inline script kept in the session log; re-runnable from tmp/analysis/)
```
