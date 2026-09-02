# The Plan → Work → Review → Repair Loop under Unknown Budgets

- **Category:** agent-architecture (loop design / budgeting)
- **Source:** web research digest (arXiv 2023–2026 + repo audit), user request 2026-09-03
- **Reviewed:** 2026-09-03

Research question: what does the literature say about the
plan → work → review → repair loop (the exact shape of the Shlepa v5 agent),
and how should such a loop behave when the total token/time budget is
**limited and unknown to the agent** (issue #63: T not exposed, token limit
never surfaced; the container is killed at the task's own limit; no prompt or
tool output may tell the agent it is tight on budget)?

## Motivation

Shlepa v5 runs an unbounded cycle: `plan (60s) → work (120s) → review (45s)`,
where the review phase is the repair step — it verifies the deliverable
mechanically, repairs it if broken, and decides `done` vs `next_round`
(a new plan/work cycle). There is no task time limit T inside the agent, no
cycle cap, no token budget; the only bounds are the per-operation caps
(`budget.py`), and the external kill at the task's limit is the only real
stop. The work phase keeps the deliverable fresh on disk, so whichever cut
happens first, a partial answer scores.

The open design question: when the budget is unknown, (a) is the
review/repair loop even worth running, and what makes it work; (b) how should
the loop decide `done` vs `next_round` and where should a fixed budget be
spent — without the agent ever being told the budget exists.

Concrete budget shape (repo audit 2026-09-03): 35 tasks — 27 at 600 s
agent timeout, 4 at 300 s (seccodebench), 2 at 900 s (cve-bench), 2 at
120 s (contest sanity). One full cycle ≈ 225 s at the regime caps, i.e.
**≈ 2.7 cycles at 600 s, ≈ 1.3 at 300 s**; the 120 s sanity tasks take the
trivial plan→commit shortcut and get no work/review cycle at all.

## Methods A — loop patterns: what makes review/repair work

| pattern | source | loop shape | what the review/repair is grounded in |
|---------|--------|------------|---------------------------------------|
| Self-Refine | [2303.17651](https://arxiv.org/abs/2303.17651) | generate → self-feedback → refine, iterations | **intrinsic** (no tools) |
| Reflexion | [2303.11366](https://arxiv.org/abs/2303.11366) | trial → evaluate → verbal reflection → retry, `while eval not pass or t < max trials` | external evaluator + episodic memory; **budget-aware by design** (max-trials cap) |
| CRITIC | [2305.11738](https://arxiv.org/abs/2305.11738) | output → tool-interactive critiquing → progressive amendment | **tools** (search, code interpreter) |
| CoVe | [2309.11495](https://arxiv.org/abs/2309.11495) | draft → plan verification questions → answer independently → verified final | independent re-derivation |
| SWE-agent | [2405.15793](https://arxiv.org/abs/2405.15793) | free interactive agent, custom agent-computer interface | environment feedback (tests, files) |
| Agentless | [2407.01489](https://arxiv.org/abs/2407.01489) | localization → repair → patch validation, **fixed control flow, LLM never decides next action** | unit-test oracle per repair loop |
| LATS | [2310.04406](https://arxiv.org/abs/2310.04406) | MCTS over agent trajectories with value function + self-reflection | environment feedback; heavy search |

Convergence pattern, with the counter-evidence:

- **Intrinsic** self-correction ("think about your answer again", no external
  signal) mostly does not help: "LLMs struggle to self-correct their
  responses without external feedback, and at times … perform worse"
  ([2310.01798](https://arxiv.org/abs/2310.01798), ICLR 2024).
- Even with iteration, self-repair gains are "often modest, vary a lot
  between subsets of the data, and are sometimes not present at all" once
  the **cost of carrying out repair is taken into account**
  ([2306.09896](https://arxiv.org/abs/2306.09896)); the bottleneck is the
  model's ability to give feedback on its own code, and a stronger model as
  feedback source gives substantially larger gains.
- Reflexion's ablation (same paper): without unit tests, the coding agent
  "is unable to determine if the current implementation is correct … must
  participate in all iterations … performing **harmful edits**".
- The wins come when the review is **externally grounded**: tool-interactive
  critique (CRITIC), unit-test oracles (Agentless: 32.0% SWE-bench Lite at
  $0.70, a *simpler* pipeline than interactive agents), mechanical
  verification against a spec. **Shlepa's review is in this family**: it
  re-reads the file, runs `jq`/format checks, and compares every required
  name/value against the task spec — not intrinsic reflection.

Quantitative anchors (verified in-paper 2026-09-03):

- Self-Refine: "5–40% absolute improvement" over direct generation across 7
  tasks, but "up to 13%" on code generation with strong code models;
  "diminishing returns … as the number of iterations increases" (marginal
  improvement decreases with more iterations); failure analysis: the majority
  of failed refinements trace to **erroneous feedback** (33% wrong error
  location, 61% inappropriate fix, only 6% faulty refinement).
- Reflexion: +22% ALFWorld (12 iterative steps), +20% HotPotQA, +11%
  HumanEval; "self-reflection is extremely useful … over **a handful of
  trials**" — the published setups cap trials.
- Agent test-time scaling ([2506.12928](https://arxiv.org/abs/2506.12928)):
  among sequential revision strategies, "the direct gains from having the
  agent perform reflection at **each** step are not obvious. Instead,
  allowing the agent to perform reflection when it performs poorly in the
  current step brings certain benefits. … **knowing when the agent should
  reflect is more important than having the agent perform reflection at every
  step directly**."

## Methods B — spending a limited budget across loop phases

| work | setting | key result |
|------|---------|------------|
| ZEBRA ([2605.20485](https://arxiv.org/abs/2605.20485)) | 4-phase pipeline **Plan → Decompose → Implement → Refine** (same shape as ours), fixed $ budget, APPS coding (150 tasks) + HotpotQA | Zero-shot per-phase budget allocation: LLM estimates per-phase saturating-exponential utility curves; water-filling on the Lagrange multiplier solves the continuous knapsack. At α=0.5 of unconstrained spend, **94.4% of unconstrained quality recovered vs 88.1% for LLM-direct allocation**; "the advantage concentrates on medium and hard tasks"; the gap "scales with tightness"; on APPS the right split is "**strongly skewed toward refine** and Uniform leaves ~5 points on the table"; on HotpotQA the right split is near-balanced (ZEBRA adapts, not memorizes). A hybrid mid-pipeline re-allocation node did **not** help on HotpotQA |
| Snell et al. ([2408.03314](https://arxiv.org/abs/2408.03314)) | fixed test-time compute budget; search (BoN) vs revision (iterative self-refinement) | Optimal mechanism **varies with prompt difficulty**; "compute-optimal" per-prompt allocation (difficulty estimation) gives **>4× efficiency vs best-of-N**; revision wins where the base model is already somewhat successful |
| Budget forcing ([s1, 2501.19393](https://arxiv.org/abs/2501.19393); [2510.21398](https://arxiv.org/abs/2510.21398)) | per-request exact token budget for thinking | A decoding intervention that allocates exact budget and "elicits the inherent self-correcting behavior"; a **per-request** lever, not a loop lever — complements rather than replaces loop-level stopping |
| Token-budget-aware reasoning ([2412.18547](https://arxiv.org/abs/2412.18547)) | CoT with explicit token budget in the prompt | Per-problem dynamic budgeting compresses reasoning "with only a slight performance reduction" — budgets must be **per-problem**, not uniform |
| EcoAgent-Bench ([2608.05519](https://arxiv.org/abs/2608.05519)) | agents with explicit per-task priced budgets (304 tasks) | "Completion under a budget and economical action selection are distinct properties"; agents fail both stopping on unsupported premises and avoiding unnecessary escalation; micro-averages reward one-sided policies — measure both directions |
| Agentic Abstention ([2606.28733](https://arxiv.org/abs/2606.28733)) | when to stop acting (28k+ tasks, 13 systems) | "The main challenge is not only whether agents can abstain, but also **when** they abstain"; some never abstain, others only after many unnecessary interactions; capability does not fix timing |
| Convergence-prediction stopping ([2607.03991](https://arxiv.org/abs/2607.03991)) | repeated Text-to-SQL runs, judge consistency trajectory | "Knowing when to stop" the repetition loop is formulated as **convergence prediction**: observe the running consistency trajectory and stop when further runs are unlikely to shift it; adapts per question (stops sooner when convergence is early) |
| Anytime algorithms (classical; e.g. [anytime A*, 1110.2737](https://arxiv.org/abs/1110.2737)) | search under unknown/external time cutoff | Every prefix of the run is a valid, improving partial solution — the property that makes an external kill survivable |

### Methods B2 — the 2026 "budget-aware agent" slice (verified 2026-09-03 from a second source)

A separate research slice treats the budget as an **agent-visible** signal. Verified against primary sources (arXiv abstracts/HTML + project READMEs):

| work | setting | key result |
|------|---------|------------|
| Budget-Aware Tool Use ([2511.17006](https://arxiv.org/abs/2511.17006): **Budget Tracker** + **BATS**) | web-search agents, explicit tool-call budgets; tracker injects current/remaining budget every round | "Simply increasing the tool-call budget fails … agents lack 'budget awareness' and quickly hit a performance ceiling"; Budget Tracker with budget=10 matches ReAct budget=100 (12.8% vs 12.6%) at **31.3% lower cost**; BATS verification decides `CONTINUE` (dig deeper) vs `PIVOT` (switch path) on remaining budget. Stated limitation: "we do not explore how an agent should allocate its available resources … models often **underestimate** their actual resource consumption" |
| BRACE ([2608.01428](https://arxiv.org/abs/2608.01428)) | embodied agents (Habitat/RoboFactory/AirSim); replanning as a budgeted control loop (decide-whether-to-replan, mode, token budget + latency SLO) | E-RECAP progressive token pruning: **62–92%** fewer replanning-call tokens; SLO violations **85.5–100% → 4.7–50%** where success is already saturated; 80% success, 4.6% SLO in a harder setting where frozen-plan fails |
| BAGEN ([2606.00198](https://arxiv.org/abs/2606.00198)) | "Are LLM agents budget-aware?" — progressive interval estimation of remaining budget, rollout-replay scoring | Budget-estimation ability **decoupled** from solving (correlation r=0.35); frontier models **over-optimistic**, keep spending on unlikely-to-succeed tasks; early-stop saves **28–64% tokens** on failed trajectories; interval coverage caps at 47% after SFT+RL |
| ALAS ([2511.03094](https://arxiv.org/abs/2511.03094)) | stateful multi-agent planning (job-shop suites); **localized repair** | Independent validator with "fresh, bounded context, avoiding **self-check loops**"; versioned execution log as **restore points**; repair edits only the minimal affected region with explicit **loop guards**; 83.7% success, **60%** token reduction, 1.82× faster vs baselines |
| R³DAO (projects: `notoufa/R3DAO`, `hustnccl/R3DAO`) | reactive multi-agent orchestration for long-horizon data-science tasks; Planner/Actor/Critic + knowledge layer | **Self-reported** (README, MLE-bench, not peer-reviewed): +77.36% success vs R&D-Agent, **36×** shorter average execution, ≤104k tokens/task; local "reactive topology reconfiguration" instead of global reset |
| FWF (project: `tbaums/fun-with-friends`) | multi-agent Claude Code dev factory; operator-set `--budget-usd`/`--token-budget` | System-side sentinel (60 s polling): on hold, every role "**commits WIP and idles** until the next tick — it never cancels a role's loop, so it resumes automatically once the hold clears"; per-run baseline so restarts don't inherit prior spend |
| TokenFuse (project: `TAIPANBOX/tokenfuse`) | Rust runtime control for agents | per-run budgets, loop detection, burn forecast, kill-switch |

**Regime note:** every entry in B2 presupposes the budget is **known** to the agent or operator; several hand it to the agent verbatim (Budget Tracker). Shlepa's constraint (#63) is the opposite — budget unknown and agent-invisible, kill terminal (no "resume after replenishment"). The transferable parts are the **system-side** mechanisms (sentinels, loop guards, restore points, localized repair), not the agent-visible trackers.

## Convergence (the load-bearing findings)

1. **Grounded review wins, intrinsic reflection does not.** The repair loop
   is worth running only when the review is mechanically/tool grounded
   (spec checks, tests, file re-reads). Shlepa's review already is.
2. **Marginal value per cycle decays fast.** Diminishing returns in
   Self-Refine; modest cost-adjusted gains in self-repair; Reflexion caps at
   a handful of trials. A `next_round` that repeats a previous defect is
   negative expected value, not a missed opportunity.
3. **Under a tight budget, spending skews toward refine/verify on coding
   tasks** (ZEBRA on APPS), and the cost of bad allocation grows as the
   budget tightens (ZEBRA; EcoAgent-Bench). Equal splits are ~5 points off
   on coding.
4. **"When to stop" is the unsolved part, not "whether to review".**
   Conditional reflection beats always-on reflection (2506.12928); abstention
   timing is a known weak point of current agents (2606.28733); stopping
   should track per-instance convergence, not a fixed iteration count
   (2607.03991).
5. **Unknown budget ⇒ anytime design + local caps + conservative stop rule**,
   not deadline estimation. The system side (per-operation caps, fresh
   deliverable on disk, developer-owned budget accounting) is the standard
   pattern; the open question is only the *agent-side stop rule* — and the
   constraint that it must work **without the budget being visible to the
   agent** (#63) means it must be expressed in loop-internal signals
   (cycle count, hint repetition, review status trajectory), never in
   remaining-time or remaining-token terms.
6. **Budget-visible trackers are a different regime** (B2): handing the agent
   its remaining budget works for *known* budgets (2511.17006), and BAGEN
   shows frontier models are bad at estimating it anyway (r=0.35 coupling,
   systematic over-optimism, "continue spending on tasks unlikely to
   succeed"). Two consequences: stop rules must lean on **mechanical loop
   signals**, never model self-assessment; and the winning machinery from
   this slice (sentinels, loop guards, restore points) is all *system-side* —
   i.e. #63-compatible as written.

## Fit for Shlepa

What v5 already has (mapped to the literature):

- Mechanical spec review = CRITIC-style grounded verification (finding 1) ✔
- Fresh-on-disk deliverable + external kill = anytime property (finding 5) ✔
- Per-operation caps, no budget in the agent prompt = system-side budgeting ✔
- Low `reasoning_effort` on review, full tools for repair = cheap verify,
  capable repair ✔
- Conservative next_round policy in `commit.md` ("only if MATERIALLY improve,
  never for polish") = partial implementation of finding 2/4 ✔

Gaps (each small, each testable with existing MLflow metrics):

- **G1 — the review decides done/next_round blind to the loop.** `work`
  sees "this is cycle N" (limits_note); `commit` does not. The review also
  does not see the previous cycle's own hints, so it cannot tell "new defect
  found" from "same defect, second time". Consequence: on a 600 s task a
  spurious `next_round` at t≈225 s spends the only remaining cycle (225 s →
  t≈450 s), and a repeat of the same defect costs a third cycle the task
  never has.
- **G2 — no repeat-defect guard.** Nothing stops two consecutive
  `next_round` verdicts with the same hints (2607.03991: stop when the
  trajectory has converged; 2306.09896: repeat repair is sometimes net
  negative).
- **G3 — uniform per-phase split.** All tasks get 60/120/45. Per ZEBRA the
  coding-optimal split skews to refine; per Snell the right mechanism varies
  by difficulty. (Dev-side knob, never agent-visible — #63-compatible.)
- **G4 — no stop-signal telemetry.** Runs don't log cycle count or the
  verdict sequence, so the value of the loop (finding 2/3) is currently
  unmeasured on our own fleet.
- **G5 — short-task edge.** The 300 s tasks (seccodebench) get one full
  cycle (225 s) plus ~75 s of slack: the second cycle is exactly the
  expensive one, so its expected value is the whole margin of the run.

## Recommendations (ranked, all A/B-testable via `shlepa run` batches)

1. **Measure first (G4):** log `cycles` and the review verdict/hints
   sequence per run (MLflow metric `cycles` + tag `review_verdicts`).
   One week of batches then answers: how often is cycle 2+ reached, how
   often do hints repeat, and does cycle 2 correlate with solved on
   otherwise-failed runs. No agent-visible change.
2. **Diminishing-returns context in the review prompt (G1):** render cycle
   number + previous-cycle hints into `commit.md` and instruct: on cycle ≥ 2
   default to `done` unless this review found a **new** defect the previous
   hints did not cover. Prompt-only; keeps the verdict honest (a genuine new
   finding still gets a cycle).
3. **Repeat-defect guard (G2):** runner-level — if two consecutive review
   verdicts are `next_round` and their hint sets are near-duplicates
   (normalized string similarity), force `done` on the second. A hard cap on
   *repeated* cycles, not on cycles in general (the budget stays
   agent-invisible; the guard fires on loop-internal signals only).
4. **Family-level phase split (G3, dev knob only):** per-task-family
   `[phases.*].time` overrides in dev presets (e.g. seccodebench: less
   plan, more work+review), mirroring ZEBRA's refinement skew — validated
   against the §G4 data, not a priori.
5. **Staged deliverable / last-verified snapshot (new, from ALAS restore
   points):** work writes to a staging path; review copies it to the final
   spec path only when its mechanical checks pass. The final path then always
   holds the last *verified* version, so a kill mid-edit of cycle N+1 cannot
   leave a half-updated file that regressed the end-of-cycle-N state.
   Implementation: prompt change in `work.md` ("write to <staging>; review
   promotes it") + one `cp` in `commit.md` step 2; keep the final path/format
   identical for the verifier.
6. **System-side budget watchdog (new, from FWF's sentinel; dev runs only):**
   the CLI/runner already knows `timeout_sec` per task; an operator-side
   watcher can force the last cycle to route to review (or skip a
   `next_round` at cycle start) once a fraction of the task limit is
   elapsed. Never agent-visible — the kill logic stays in the harness, exactly
   as FWF keeps its sentinel outside the role prompts. Contest submission:
   no watchdog (T is unknown there) — per-operation caps + anytime file only.
7. **Keep the anytime invariant audited (G5):** spot-check traces of the
   120 s sanity tasks and any future short-limit tasks: deliverable on disk
   at kill, review not required to run.

**Do NOT:** expose remaining time/tokens to the agent (violates #63); add a
global token budget or request-count gate (removed in v5 on purpose); make
the review *more* permissive on `next_round` (finding 2).

## Risks / honest gaps

- More conservative stopping may forfeit genuine cycle-2 gains on wrong
  deliverables. Mitigation: A/B on seccodebench (4 tasks, 300 s — the
  tightest real budget) + 2–3 CTF with N≥2–3 repeats, comparing `solved`
  and `tokens_total` (repo A/B culture; cf. active `ab-runs` plan).
- ZEBRA/Snell optimize a **known** dollar/FLOPs budget (α given); Shlepa's
  novelty is the agent-side **unknown** budget. The transfer — "skew to
  refine, stop on convergence, anytime file" — is a design argument, not a
  benchmark result. No head-to-head of "unknown-budget agent loop" designs
  was found; that gap is real as of 2026-09-03.
- The entire B2 slice (BRACE / Budget Tracker+BATS / BAGEN / ALAS / R³DAO /
  FWF / TokenFuse) assumes the budget is **known** to the agent or operator,
  and several assume a *replenishable* budget (FWF pause/resume) — infeasible
  here (terminal kill). Their agent-visible-tracker results do not bound our
  design; only their system-side mechanisms do.
- R³DAO's 36× / 104k / +77.36% figures are **project self-reports on
  MLE-bench** (README; not peer-reviewed; no public benchmark harness
  located). Treat as anecdotal.
- ZEBRA's "~5 points" and "skewed toward refine" are for a 4-phase pipeline
  (Plan/Decompose/Implement/Refine) with its own phase semantics; our
  `work` ≈ Implement and our `review` ≈ Refine-plus-verifier, but the
  mapping is ours, not the paper's.
- EcoAgent-Bench measures agents that *know* their budget (priced actions);
  its stopping findings transfer by analogy only.

## Sources

Verified against primary sources 2026-09-03 (arXiv abstracts + HTML where
cited quantitatively):

- Self-Refine: https://arxiv.org/abs/2303.17651
- Reflexion: https://arxiv.org/abs/2303.11366
- CRITIC: https://arxiv.org/abs/2305.11738
- Is Self-Repair a Silver Bullet for Code Generation?: https://arxiv.org/abs/2306.09896
- Chain-of-Verification: https://arxiv.org/abs/2309.11495
- Large Language Models Cannot Self-Correct Reasoning Yet: https://arxiv.org/abs/2310.01798
- Language Agent Tree Search: https://arxiv.org/abs/2310.04406
- SWE-agent: https://arxiv.org/abs/2405.15793
- Agentless: https://arxiv.org/abs/2407.01489
- Scaling LLM Test-Time Compute Optimally (Snell et al.): https://arxiv.org/abs/2408.03314
- Token-Budget-Aware LLM Reasoning: https://arxiv.org/abs/2412.18547
- s1: Simple test-time scaling (budget forcing): https://arxiv.org/abs/2501.19393
- Scaling Test-time Compute for LLM Agents: https://arxiv.org/abs/2506.12928
- ZEBRA: Zero-shot Budgeted Resource Allocation for LLM Orchestration: https://arxiv.org/abs/2605.20485
- Agentic Abstention: Do Agents Know When to Stop Instead of Act?: https://arxiv.org/abs/2606.28733
- Knowing When to Stop: Predicting Execution-Consistency Convergence in Text-to-SQL: https://arxiv.org/abs/2607.03991
- EcoAgent-Bench: Evaluating Economic Decision-Making in Budget-Constrained LLM Agents: https://arxiv.org/abs/2608.05519
- Anytime heuristic search (classical anytime pattern, modern reference): https://arxiv.org/abs/1110.2737
- RL for budget forcing (context): https://arxiv.org/abs/2510.21398
- Budget-Aware Tool Use Enables Effective Agent Scaling (Budget Tracker + BATS): https://arxiv.org/abs/2511.17006
- BRACE: When Replanning Becomes the Bottleneck: Budgeted Replanning for Embodied Agents: https://arxiv.org/abs/2608.01428
- BAGEN: Are LLM Agents Budget-Aware?: https://arxiv.org/abs/2606.00198
- ALAS: Transactional and Dynamic Multi-Agent LLM Planning: https://arxiv.org/abs/2511.03094
- R³DAO (self-reported figures): https://github.com/notoufa/R3DAO
- FWF (fun-with-friends; budget sentinel + commit-WIP): https://github.com/tbaums/fun-with-friends
- TokenFuse (agent runtime budget control): https://github.com/TAIPANBOX/tokenfuse
- awesome-loop-engineering (curated list, 989 resources): https://github.com/ChaoYue0307/awesome-loop-engineering
- Repo: issue #63, `docs/agent-config.md` (Bounds section), `agent/shlepa_agent/budget.py`,
  `agent/shlepa_agent/phases/`, `tasks/*/task.toml` (timeout distribution)

Unverified: the "4× efficiency" reading of Snell et al. is the paper's own
claim (FLOPs-matched, PRM setting) and is reported as such; ZEBRA's exact
per-phase α=0.3 split numbers (appendix D.9) not extracted here; BRACE's
"ICML 2026" venue (only the 2026-08 arXiv preprint located). From a second
(LLM-generated) source list cross-checked 2026-09-03: a "Debug-Agent with
max 600 rounds" kill switch could **not** be located (arXiv or GitHub) —
recorded here as likely hallucinated; the unnamed "atomic DAG scheduling +
cross-session persistence" project is unverifiable as cited (the concepts do
appear in ALAS / R³DAO / FWF).

**Track:** the G4 (stop-signal telemetry) and G1/G2 (prompt + guard) items
are GitHub-issue candidates via the `backlog` skill when picked up.
