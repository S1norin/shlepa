# v6 End-State: Complete Pipeline Plan

Status: **agreed end-state, 2026-09-02 (uncommitted).** This is the single view of v6. The
three companion plans are the detailed unfoldings with evidence and references — this document
is what we build, phase by phase, in what order, and what it fixes / doesn't touch / opens.

- `docs/plans/agent-v6-pipeline-hardening.md` — F1–F3 evidence base, PLAN/WORK boundary (Wave 1)
- `docs/plans/agent-v6-review-redesign.md` — F2 evidence base, REVIEW redesign (Wave 2),
  §10 Deferred ideas (IDEA-1: oracle early-exit — recorded, **not enabled**)
- `docs/plans/agent-v6-stagnation-guard.md` — loop/stagnation + budget layer (Wave 3)
- `docs/analysis/2026-09-02-review-drift-census.md`, `docs/analysis/2026-09-02-stagnation-replay.md`
  — the 474-trace offline data (R1 gate passed)

Key standing decisions:

1. **Strictly linear pipeline — no shortcuts** (2026-09-02). Every task, trivial included,
   flows PLAN → WORK → REVIEW. The v5 `decision="commit"` plan→commit path is removed;
   `decision` leaves `PlanResult`.
2. **Oracle early-exit is deferred** (IDEA-1, review-redesign §10). The post-work mechanical
   check always routes to REVIEW in the current scope.
3. **No mechanism may condition behavior on the unknown per-task time/token limit.** Budget
   logic uses known quantities only (phase caps, own elapsed, own token usage) or observed
   signals (endpoint errors). Strategy: be fast, always exit normally.

---

## 1. The pipeline when we finish

```
run.sh "<instruction>"
│
├─ STAGE 0  BOOTSTRAP (harness, no LLM)
│    clock, redacting logger, telemetry (dev-only, optional), budget state,
│    test-file hashes (tamper guard), batch/task metadata
│
├─ STAGE 1  PLAN — cap 30 s — tools: read + recon + search (NO bash/write/edit)
│    → PlanResult{goal, findings, steps[], risks[], artifact_spec}
│      artifact_spec = {kind: file|test_command|answer, path, format, keys[, expected_content]}
│    exits: success → WORK · timeout → PARTIAL_HANDOFF → WORK · error → WORK (direct-execution note)
│
├─ STAGE 2  WORK — cap 120 s — tools: read + write + edit + bash + recon + search
│    fresh conversation; plan state arrives as a structured block (never the plan transcript)
│    → WorkResult{summary, deliverable}; write the deliverable EARLY, refine later
│    exits: success | timeout | error → all go to the post-work check (whatever is on disk)
│
├─ STAGE 3  POST-WORK CHECK (harness, no LLM, milliseconds)
│    deliverable_check(workdir, path, artifact_spec) → {exists, non_empty, parse_ok, keys_ok, valid}
│    ├─ missing/empty → SALVAGE (write-only, ≤30 s, fresh) → re-check
│    └─ (always) → REVIEW
│    [IDEA-1, deferred — review-redesign §10: if ever enabled, `valid ∧ oracle=true`
│     (exact expected content verbatim in the instruction) would EXIT done here with no LLM
│     review. Not in the current scope.]
│
├─ STAGE 4  REVIEW — cap 45 s total (subcaps 15/20/10, separate requests)
│    FRESH context packet: spec + artifact (preloaded) + check results + decision summary + last-tools
│    ├─ VERIFY  ≤15 s — tools: read + search (no bash/write/edit), artifact preloaded
│    │    → ReviewResult{status, verdict, repair_scope: none|local|deep, failed_checks[], hints[]}
│    │    PASS → EXIT done
│    ├─ REPAIR  ≤20 s — only on repair_scope=local + named failed check;
│    │    tools: read + search + edit (artifact file only, NO bash), ≤1 mutation
│    │    → harness re-runs deliverable_check: pass → EXIT done · fail → next_round
│    └─ decide  ≤10 s — short separate request; the 45 s kill can never erase "work + decide"
│
├─ STAGE 5  NEXT_ROUND — trigger: ONLY a named strict-check failure that local repair cannot
│    close (no time condition — limits are invisible; no "could be better" — binary scoring)
│    hints → fresh PLAN → WORK → … (loop)
│    artifact snapshot after every round; at exit we deliver the last check-passing (else best) artifact
│
├─ BUDGET LAYER (all phases)
│    • budget header in every request: [phase=… elapsed=… remaining=…] (known quantities only)
│    • finalization reserve: last R seconds of a phase cap → deliverable writes only
│    • failure ledger: 2nd+ identical failed tool result → compact line (first never compressed)
│    • stagnation Level A: shadow-only (log, no hard blocks)
│    • endpoint_finalized: consecutive 429/402/endpoint errors → stop, best-file, normal exit 0
│
└─ EXIT PATHS (all = normal run.sh exit unless externally killed)
     done → exit 0 · endpoint_finalized → exit 0 · budget exhaustion → finalize + exit 0
     external kill at the (invisible) task limit → 0; mitigation = be fast + always exit normally
```

## 2. Phase-by-phase walkthrough

### Stage 0 — Bootstrap (harness, no LLM)

- The only input is `run.sh "<instruction>"`; env carries only `LOCAL_AGENT_MODEL`,
  `OPENAI_BASE_URL`, `OPENAI_API_KEY`; the container has `jq`, `python3`, `ripgrep`
  preinstalled, no internet, no runtime installs.
- The harness starts the monotonic clock, the redacting event logger, telemetry (dev-only;
  never in the submission), and the budget state.
- If the task ships in-environment test files, their hashes are recorded now (tamper guard:
  a mutated test suite invalidates its own results).

### Stage 1 — PLAN (cap 30 s, tools: `read` + `recon` + `search`)

- **Input:** the instruction + system prompt (task category, recon script) in a **fresh
  conversation** — also fresh on replan cycles; the previous cycle's `WorkResult` summary and
  REVIEW hints arrive as a structured user block, never as raw transcript.
- **What the model may do (and only that):**
  1. Read the instruction and extract the exact deliverable spec (path, format, required
     keys/fields, constraints).
  2. `recon` — the deterministic surface map: `recon <url>` (live target),
     `recon --code <dir>` (source tree), `recon --data <dir>` (evidence dir). Flat JSON,
     ≤8 KB, hard 25 s internal cap, read-only by construction.
  3. `search` — targeted confirmations (specific strings, file patterns, directory listing);
     capped output (≤8 KB, total match count + first N matches).
  4. `read` — a few known-path files.
- **What it structurally cannot do:** start the work. No `bash` (no exploits, no bulk
  analysis, no long commands), no `write`/`edit` (no deliverable, no scratch). This is the
  fix for the 42% plan-cap cohort (31% 35B / 71% 27B) where capped plans made 40+ real-work
  tool calls.
- **Output contract:** typed `PlanResult{goal, findings, steps[], risks[], artifact_spec}` via
  the output tool. **No `decision` field** — the pipeline is linear; the next phase is always
  WORK.
- **Exit transitions (the PLAN→WORK boundary, in all three outcomes):**
  - *Success* (typed output within 30 s): WORK receives the full `PlanResult` as a
    structured block.
  - *Timeout* (30 s): the harness fires `final_ask(PARTIAL_HANDOFF)` — a short, tool-less,
    **typed** request for the partial plan state; WORK receives the handoff JSON +
    deterministic `LAST_TOOLS` (last 6 tool calls, args ≤200 chars, results ≤400 chars) + the
    note "may be incomplete; write the deliverable early". This is the routing invariant:
    **WORK can no longer be skipped** (v5's `plan timeout → final_ask → commit` shape,
    12% of runs at 17% solved, is gone by construction).
  - *Error*: WORK gets a direct-execution note and plans minimally from the instruction text.
- **Why 30 s:** calibrated so recon (≤25 s) plus a few reads fit. If the model is still
  exploring at second 30, it is working, not planning — and the handoff takes over.

### Stage 2 — WORK (cap 120 s, tools: `read` + `write` + `edit` + `bash` + `recon` + `search`)

- **Input:** fresh conversation; the plan state (full `PlanResult` or partial handoff) as a
  structured user block.
- **What the model does:** executes the steps; **writes the deliverable to the declared path
  early and refines it** (the deliverable is an anytime-on-disk invariant for the normal-exit
  rule); for `kind=test_command` tasks it runs the in-environment test suite (the repo's own
  pytest/npm suite — never the hidden verifier) as its own external feedback; `search`/`recon`
  are available for structured, token-lean exploration; `bash` remains the escape hatch for
  anything genuinely shell-shaped.
- **Output:** typed `WorkResult{summary, deliverable}`.
- **Exit transitions:** success, timeout, and error **all** flow into the Stage 3 check — the
  check runs on whatever is on disk. A timed-out WORK with a half-written file is handled the
  same way as a completed one; nothing routes around the check.

### Stage 3 — Post-work check (harness, no LLM)

- `deliverable_check(workdir, path, artifact_spec)` — a pure function: `{exists, non_empty,
  parse_ok, keys_ok, valid}` + a logged event. No interpretation, no LLM.
- **Routing:**
  - *missing/empty* → **SALVAGE**: a write-only phase (≤30 s, fresh, `write` only) given the
    spec and whatever context is cheap; the harness additionally persists
    `final_result.body` atomically (tmp file + rename) if the model itself never wrote.
    Re-check after. Kill-switch `SHLEPA_SALVAGE=0`. (Census: 37.5% of capped runs were
    writing files inside the review cap and died mid-write — salvage moves that writing to a
    dedicated, bounded, disk-guaranteed window.)
  - *otherwise* → REVIEW.
  - [IDEA-1, deferred: the oracle early-exit branch — `valid ∧ oracle=true` (exact expected
    content verbatim in the instruction, verbatim-substring anchor) → EXIT done,
    `commit=skipped_oracle` — is recorded in review-redesign §10 with its full spec, safety
    argument, and re-enablement gate. **Not enabled.** Trivial tasks therefore flow
    PLAN → WORK → REVIEW like everything else; they stay fast because WORK is cheap and the
    mechanical check keeps REVIEW short.]

### Stage 4 — REVIEW (cap 45 s total; subcaps 15/20/10 as separate requests)

- **Context:** a **fresh conversation** built by the harness from a packet —
  `artifact_spec` + the artifact (preloaded) + `deliverable_check` results + the decision
  summary (plan goal + work summary) + compact `LAST_TOOLS`. Not the work transcript: the
  "keep doing what I was doing" salience (the drift engine: 33% of capped runs were pure
  exploratory) is removed structurally, and the Cognition communication-bridge caveat is
  honored by the decision summary.
- **VERIFY (≤15 s, tools: `read` + `search`; no bash/write/edit):** the model has no means to
  work or repair — only to judge. It checks the artifact against the spec and may search the
  corpus for evidence (e.g. "does this IOC/flag value actually occur in the provided data?").
  Output: typed `ReviewResult{status, verdict, repair_scope: none|local|deep,
  failed_checks[] (named, e.g. "key X missing"), hints[]}`. A failure must be named — "the
  file is bad" is not an acceptable check.
  - `PASS` / verdict ok → **EXIT done**.
  - `repair_scope=local` + named failed check → REPAIR.
  - `repair_scope=deep` (or the failure is not locally closeable) → **next_round** with
    hints — the investigation belongs in a new PLAN→WORK cycle, not in the final window.
- **REPAIR (≤20 s, tools: `read` + `search` + `edit`, artifact file only, NO bash,
  ≤1 mutation):** only for local failures. After the mutation the **harness re-runs
  `deliverable_check`** — external feedback, not the model's claim that it fixed it. Pass →
  EXIT done; fail → next_round (no debug loop in the terminal window; Olausson: combined
  verify+repair only pays with crisp external feedback).
- **Decide (≤10 s, separate short request):** the verdict is its own request, so the 45 s kill
  can never erase "work + decide" in one in-flight stream (v5 had 138 traces with no
  `ReviewResult` at all). At any kill moment the state of the last completed step is on record.
- **Artifact regression guard:** the harness snapshots the artifact after every round; at
  exit the delivered artifact is the last check-passing one (else the best). A killed round 2
  can't overwrite a good round 1 file.

### Stage 5 — NEXT_ROUND (the recovery loop)

- **Trigger discipline:** only a named strict-check failure that local repair cannot close.
  Never on "could be better" (polish is worth 0 under binary scoring), never conditioned on
  time (the task limit is invisible to the agent — there is no time gate). The deliverable is
  already 0; a killed new round is 0 either way; the only difference is second-order
  tie-break tokens, which never outweigh a point.
- Hints from `ReviewResult` enter the fresh PLAN as a structured block; the plan must address
  them and not repeat what failed.
- **Budget layer (all phases):** the budget header (`[phase/elapsed/remaining]`) uses only
  known quantities (our own phase caps, our own clock, our own token usage) — never a guessed
  deadline or token cap. Finalization reserve: the last R seconds of a phase cap accept
  deliverable writes only (exploratory calls get a synthetic `FINALIZING` result). Failure
  ledger: from the second occurrence, identical failed tool results are compressed to a
  one-line (family + exit code); the first occurrence is never compressed. Stagnation Level A
  is shadow-only (the 474-trace replay found 0 strict candidates — enforcement without a
  target is false-positive risk only). `endpoint_finalized`: consecutive terminal endpoint
  failures (429/402/5xx storm — the only *observable* proxy for hitting an invisible external
  token cap) stop new requests, persist the best artifact, and exit `run.sh` **normally**.
- **Strategy principle:** be fast and always exit normally. Every second/token saved is
  (a) a better tie-break, (b) a smaller window in which the unknown kill lands on useful work,
  (c) an earlier normal exit — the only state in which the verifier runs at all.

## 3. Problems this solves

| # | Problem | Evidence | Fixing mechanism |
|---|---|---|---|
| S1 | Model **works in PLAN**; WORK gets skipped on plan timeout | plan cap in 42% of runs (31% 35B / 71% 27B); double-capped shape = 12% of runs at 17% solved vs 61% | PLAN tools = read+recon+search (bash/write/edit absent by construction) + 30 s cap + **routing invariant** (plan timeout → PARTIAL_HANDOFF → WORK; plan error → WORK) + linear pipeline. Work in plan is structurally impossible; WORK is structurally unskippable |
| S2 | **REVIEW drift**: the terminal window spends itself on new work instead of verifying | capped cohort 30.4% (144/474) at 22.2% solved vs 59.7/64.5 clean; 76% of capped runs had tool calls in REVIEW, 33% pure exploratory | read-only VERIFY (the affordance is removed, not policed by prose) + fresh context packet (no "keep doing what I was doing") + subcaps 15/20/10 as separate requests |
| S3 | **No artifact at exit**: files written inside the 45 s cap, killed mid-write | 37.5% of capped runs wrote during the cap (H2) | harness `deliverable_check` before REVIEW + SALVAGE (write-only ≤30 s, harness atomic persist) + finalization reserve (last R s = deliverable writes only) |
| S4 | **Recovery loop is dead**: `next_round` fired 1/474; `status=ok` in 334/336 including ~40% of real failures | census; binary scoring makes "could be better" worthless | trigger moved from model mood to a **named mechanical check failure** (`failed_checks[]`) that local repair can't close; binary framing replaces "a partial deliverable scores better than nothing" in the commit prompt |
| S5 | **The 45 s kill erases the verdict**: 138 traces with no `ReviewResult`; one in-flight request (llm wall 180 s) can own the whole phase | llm_wall 180 > REVIEW_CAP 45 | subcaps as separate short requests — at any kill moment the last completed step's state is recorded |
| S6 | **Tokens + wall time (tie-break)** | official tie-break: tokens first, then wall time | fresh-context VERIFY (fewer input tokens), capped `search` instead of unbounded bash output, ledger compression, early exits, salvage instead of re-writing — "be fast", no deadline estimation (IDEA-1 oracle-exit would add more, but is deferred) |
| S7 | **Blindness**: false loop signals (256 FPs), root span without I/O, `final_ask` without a span, dangling MLflow runs, "14/14 no traces found" | F3/F4/F5/F7 confirmed in code | digest attribute keys (#68), root-span I/O (#70), final_ask span, close runs in `finally` (#35), paged trace-export, phase-id labels (#72), token/cache metrics (#73/#74/#71) |
| S8 | **External token cap / endpoint death → crash → 0** | per-task token limits exist officially and are invisible; crash = 0 | **reactive** `endpoint_finalized` on consecutive 429/402/endpoint errors → stop, best-file, normal exit 0; zero guessed numbers |
| S9 | **Blind plan**: after removing bash from PLAN, the model could only read known paths (recon maps surfaces but does not search strings) | construction fact: recon.py = surface map, no search | `search` tool (grep/glob/ls, ≤8 KB, stdlib) in PLAN/VERIFY/REPAIR/WORK — formalizes backlog #54 (smart-grep, previously +4 pt at n=1 = noise, to be re-measured n≥5) |

## 4. Problems this does NOT touch

- **N1. SOC-detection wall (0–1% solved, six-task family).** The agent finds evidence but
  never converges on the expected answer format (SOCBench verdict taxonomy, MITRE technique,
  verbatim IOC). The pipeline makes review honest; it does not teach the taxonomy. Separate
  work (pipeline item 4.3: analyze 2–3 task specs + answer-format convergence step, own mini
  A/B).
- **N2. Model ceiling.** 27B 41.8% vs 35B 49.8% — part of the gap is model quality
  (reasoning, instruction-following). Structural fixes close the gap toward the ceiling; they
  don't raise the ceiling.
- **N3. Hard CTF requiring a real solution chain (whyos/tablez, 0/14).** If deriving the
  answer needs a reasoning chain the model can't pull off, no pipeline saves it; the pipeline
  only guarantees found evidence reaches the file and gets honestly checked.
- **N4. Hidden per-task limits.** Invisible by design (the only input is
  `run.sh "<instruction>"`); we mitigate (speed, normal exit, reactive finalization), we
  cannot know.
- **N5. Hidden verifier ground truth.** Expected values inside the verifier's
  `tests/test.sh` are invisible to the agent; mechanical proxies (format + evidence
  consistency) are necessary but not sufficient.
- **N6. Task environments** (flaky services, environment-side timeouts, container OOM) — not
  our layer.

## 5. Problems this POTENTIALLY OPENS (new risks + mitigations)

| # | Risk | Mitigation |
|---|---|---|
| R-a | **Over-restriction false negatives:** read-only VERIFY+search can't catch "needs to run something to verify behavior" | `search` covers quick corpus greps; the rest is accepted: behavioral checks stay in WORK rounds; the R5 A/B (G1/G2/G3) measures the false-done rate directly |
| R-b | **Artifact regression:** round 2 overwrites a good artifact with a bad one, then gets killed → was 1, becomes 0 | harness snapshots the artifact after every round; exit delivers the last check-passing (else best) artifact; WORK in round ≥2 reads the existing artifact first |
| R-c | **Early-exit false positives** (IDEA-1 only — deferred) | the risk lives with the idea: the verbatim-substring anchor + zero-LLM comparison make false "done" impossible by construction; the re-enablement gate (false-done = 0 on exact-content families) is in review-redesign §10 |
| R-d | **Fresh-context reviewer false rejections** of deliberate choices (Cognition's own communication-bridge caveat) | decision-summary bridge in the packet; `SHLEPA_REVIEW_CTX=full` kept as an A/B arm |
| R-e | **Search truncation:** "N matches, showing first M" → the model concludes "absent" beyond the cap | output always carries the total count; 8 KB cap validated on our corpus (whyos data) in the A/B |
| R-f | **Measurement confound:** telemetry changes simultaneously with behavior | A0 = v5 behavior on the NEW telemetry (knobs `SHLEPA_ROUTE_PLAN_TIMEOUT=commit`, `SHLEPA_HANDOFF=off` reproduce v5 bit-for-bit); success criteria on the A0→winner delta |
| R-g | **next_round burns time/tokens** on tasks unsolvable within the limit (the round dies → 0 anyway) | accepted cost: the deliverable is already 0; the trigger is a named check failure only, never "try again" |
| R-h | **Salvage writes a wrong file** | not worse than absence (0 → 0); window ≤30 s; kill-switch `SHLEPA_SALVAGE=0` |

## 6. Fixes we make now (ordered waves)

**Wave 0 — observability (no behavior change):**
0.1 F3: correct attribute keys in `trace_digest` (#68) · 0.2 F4: root-span
`input/output.value` + `final_ask` span (#70) · 0.3 F5: `finally: set_terminated(FAILED)` in
`log_task_to_mlflow` + post-batch sweep (#35) · 0.4 F7: paged `trace-export` + time filter ·
0.5 #72 phase-id on tool spans · 0.6 #73/#74/#71 token/cache metrics.

**Wave 1 — PLAN/WORK boundary (linear pipeline):**
1.1 `recon` tool (wrapper over `tools/recon.py`, 25 s cap, ≤8 KB) · 1.2 `search` tool
(grep/glob/ls, ≤8 KB, stdlib-only) · 1.3 PLAN tools = [read, recon, search], `PLAN_CAP = 30` ·
1.4 routing invariant: plan timeout → PARTIAL_HANDOFF → WORK; plan error → WORK
(table-driven routing tests, all 6 PLAN/WORK outcomes) · 1.5 `PartialHandoff` typed model +
deterministic `LAST_TOOLS` (N=6, capped) into the WORK block · 1.6 WORK gains `recon` +
`search` · 1.7 **remove `decision` from `PlanResult` — strictly linear, no plan→commit
shortcut; trivial tasks flow PLAN→WORK→REVIEW** · 1.8 knobs: `SHLEPA_ROUTE_PLAN_TIMEOUT`,
`SHLEPA_HANDOFF`, `SHLEPA_SEARCH` + docs.

**Wave 2 — REVIEW redesign:**
2.1 `deliverable_check.py` (pure function + event) · 2.2 PLAN emits `artifact_spec` in
`PlanResult` · 2.3 SALVAGE route (write-only ≤30 s, harness atomic persist, kill-switch) ·
(oracle early-exit — **deferred, IDEA-1, review-redesign §10 — not in this wave**) · 2.4 VERIFY
read-only (read + search, fresh packet) · 2.5 REPAIR bounded (artifact-only, ≤1 mutation,
harness re-check) · 2.6 subcaps 15/20/10 as separate requests · 2.7 prompt rewrite: binary
framing replaces "partial better than nothing" · 2.8 next_round = named check failure, hints
into fresh PLAN · 2.9 artifact snapshot + best-at-exit (R-b).

**Wave 3 — budget / robustness:**
3.1 budget header `[phase/elapsed/remaining]` (known quantities only) · 3.2 finalization
reserve (last R s of a cap → deliverable writes only) · 3.3 failure ledger compression (knob) ·
3.4 stagnation Level A shadow-only · 3.5 `endpoint_finalized` (reactive 429/402/error
finalization, exit 0) · 3.6 test-file hash guard (tamper → test results invalidated).

**Wave 4 — experiments:**
4.1 A0 (v5 behavior on new telemetry) → winner arm · 4.2 mini A/B (de-biasing) · 4.3 full
sweep 35B · 4.4 27B check (the 71% cohort) + #58 re-measurement (search, n≥5/task) · 4.5
success criteria: +6…+10 pt (ceiling +13), capped cohort ≥ +20 pt (12%→≥32%), double-capped →
0 by construction, clean 3-phase shape ≥ 65%, hello-file 100%, plan-phase tokens ↓,
time-to-first-deliverable-write ↓.

## 7. Cross-references

- Detailed plans (evidence, AC, references): `agent-v6-pipeline-hardening.md` (W1),
  `agent-v6-review-redesign.md` (W2, §10 deferred ideas), `agent-v6-stagnation-guard.md` (W3).
- Data: `docs/analysis/2026-09-02-review-drift-census.md` (R1 gate: H1 confirmed, H3 rejected
  as score lever, H4 confirmed), `docs/analysis/2026-09-02-stagnation-replay.md` (Level A
  safe-but-inert → shadow-only).
- Telemetry defects confirmed in code: F3 (digest keys), F4 (root-span I/O), F5 (dangling
  runs), F7 (non-paginated trace-export).
- Backlog: #68, #70, #35, #72, #73/#74/#71, #58, #66, #64.
- Deferred: IDEA-1 oracle early-exit (review-redesign §10) — re-enablement gated on
  `false-done` = 0 on exact-content families.
