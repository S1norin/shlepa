# Stagnation replay — Level A offline replay on 474 traces (2026-09-02)

Companion data pack for [`agent-v6-stagnation-guard.md`](../plans/agent-v6-stagnation-guard.md)
(phase A gate). Deterministic replay only; no LLM judge.

## 1. Data and method

- Same corpus as the [REVIEW drift census](2026-09-02-review-drift-census.md):
  **474 traces**, 14 batches (35B/27B), 2026-08-31 → 2026-09-01.
- Script: `tmp/analysis/stagnation_replay.py`; output:
  `tmp/analysis/stagnation_replay/stagnation_replay.jsonl`.
- Level A candidate (the plan's enforcement rule): a run of **≥3 consecutive
  identical tool attempts within one phase**, where identity = whitespace-
  normalized exact tool key (bash: normalized `command`; others: sorted
  normalized args) **and** identical outcome fingerprint (normalized tool
  result with volatile `spent=…s ended_at=…s` envelope stripped, exit code
  preserved) **and** adverse/no-op outcome.
- Because the strict rule returned zero, three relaxed variants were replayed
  to bound the question "is there waste that Level A would structurally miss?"

## 2. Results

| Variant | Definition | Hits |
|---|---|---|
| **Level A (strict)** | ≥3 consecutive identical key + identical adverse outcome | **0 traces, 0 candidates** |
| Consecutive re-run | ≥2 consecutive identical key, any outcome | 1 trace |
| Fuzzy consecutive | ≥2 consecutive bash commands, difflib ratio ≥ 0.8 | 0 |
| Non-consecutive repeats | ≥3 identical key anywhere in one phase (any outcome) | 19 traces (4.0%) |

The 19 non-consecutive repeat traces were manually sampled: they are
**legitimate iteration**, not stuck loops — re-reading the same source file
after an edit, and re-running the same `pytest` command after a fix. Exit
codes across the repeats differ (fail → pass or changing output), which is
exactly what distinguishes "retry after state change" from "stuck".

## 3. Interpretation

1. **Literal loops do not exist in this corpus.** Neither model ever repeats a
   command verbatim back-to-back, let alone three times with the same outcome.
   The models *reformulate every attempt* — which is also why exact-match
   detection has zero targets by construction.
2. **The stagnation plan's core enforcement rule (Level A) is safe but inert on
   this data.** Zero false positives is good; zero true positives means the
   guard, as specified, would never fire on the observed failure mode.
3. **Where the budget actually leaks** (see the census companion): the
   terminal REVIEW phase (30.4% of traces capped, 22.2% solved there) and
   exploratory re-derivation that *looks like new work every step*. That is
   drift, not repetition — the exact behavior class the plan scoped out of
   Level A and assigned to Level B (log-only) plus the REVIEW redesign.
4. **Fuzzy exact-ish matching (Level B) is confirmed to be low-signal too**:
   consecutive near-duplicate bash retries at ratio ≥ 0.8: **0**. The 4%
   non-consecutive repeats are the benign kind. A similarity-based enforcer
   would add false-positive surface with no visible target on this corpus.

## 4. Verdicts for the plan gate

| Plan item | Status after replay |
|---|---|
| Level A enforcement (Phase B) | **Downgrade to shadow-only.** Keep the ledger + log; drop the hard "stop retrying" branch from the initial ship. Revisit only if shadow data shows a strict candidate actually firing in production. |
| Failure ledger (Phase D, context compression) | **Unchanged.** The 19 repeat-trace runs and the adversarial-outcome ledger entries are real signal for the model-visible summary even though they are benign behavior. |
| Level B fuzzy detector | **Log-only, no enforcement.** Consistent with the no-fuzzy-blocking constraint; replay shows it would currently log almost nothing on the main model pair. |
| Budget header / finalization reserve (Phase C) | **Unchanged** — orthogonal to repetition detection. |
| Threat model | The plan's "waste = equivalent attempt ∧ adverse outcome ∧ no state change" formula holds, but the *observed* population of such waste is the REVIEW-phase drift documented in the census, which the REVIEW redesign (commit barrier + split) addresses more directly than a retry guard would. |

## 5. Residual risk

- Corpus is 2 models × one 34-task sweep. A model that *does* loop (e.g. a
  weaker CI endpoint model, or a future 27B-class regression) would hit Level A
  exactly as designed; keeping the shadow ledger means we would see it fire
  without having enforced on false positives.
- Non-consecutive repeats were sampled, not exhaustively audited; the 19-trace
  set is in `stagnation_replay.jsonl` for manual review.

## 6. Reproduce

```bash
uv run --project cli --no-sync python tmp/analysis/stagnation_replay.py tmp/trace-export/*/
```
