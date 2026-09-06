# Read-only Plan Phase: Toolset, Budget, and Prompt Design

- **Category:** agent-architecture (pipeline design / phase gating)
- **Source:** user request 2026-09-06 (recon into baseline + a read-only plan
  phase in the budgeted regime), trace analysis of all 335 v3-loop runs
  (`tmp/trace_runs.json`, `tmp/trace_details.jsonl`), local search-bench
  (`research/code_search/analysis/search_bench_20260831-1600.md`), web research
  2026-09-06
- **Reviewed:** 2026-09-06
- **Related:** `v3loop-regime.md` (the budgeted main→commit regime),
  `plan-work-review-loop.md` (budget allocation literature),
  `readonly-tools.md` (read-only tool patterns), `recon-tool-conversion.md`
  (recon as a registered tool — already implemented)

## Motivation

The v3 regime (`[agent].loop = "v3"`) is a single budgeted main phase.
Across all 335 v3 runs the dominant failure mode is **wandering**: failed
runs spend ~2× the fresh tokens of solved runs (baseline: 60.6K solved vs
117.2K failed), almost always by re-exploring and re-verifying, not by
missing evidence. The trace data shows a natural, cheap **orientation
prefix** at the start of every good run, ending at the first
write/edit. A dedicated **read-only plan phase** makes that prefix explicit,
bounded, and arm-agnostic — and it is the natural home for `recon`, which
the user wants in the baseline.

## What the data says (local, 335 v3 runs)

**Orientation profile — tools before the first write/edit (bash arms):**

| family | n | pre-reads | pre-bash | pre-recon | total pre-tools |
|---|---|---|---|---|---|
| soc | 216 | 3.8 | 1.1 | 0.00 | 5.1 |
| seccodebench | 30 | 3.5 | 1.0 | 0.10 | 4.7 |
| ctf | 30 | 0.6 | 22.8 | 0.10 | 23.5 (work is bash-driven) |
| cve | 12 | 5.8 | 24.7 | 0.08 | 30.5 (work is bash-driven) |

Work (first write/edit) starts at tool index **4–5** (median) on SOC and
seccodebench runs. So SOC/seccode orientation is ~5 tool calls / ~4–6
chats / ~30–50s; CTF/CVE orientation is short (recon + 1–2 reads) because
their "work" is a long bash session that starts immediately.

- **Recon-first runs win on code tasks:** seccodebench cwe1336 +recon =
  5 chats / 11s vs baseline 8 chats / 20s. Recon cost: ~665ms, ≤8KB JSON.
- **Search tools in the free-form main were not used** (code_search 2 calls
  / 98 runs; log_triage 1 / 49; file_outline 1 / 49) — usage was never
  steered. A plan phase with explicit tool-first guidance is a different
  regime; the search-bench already predicts the engine outcome (below).
- **The read-only ablation was a whole-run result, not a phase result:**
  smug-dino read-only = 66 chats / 82s / ~1.7M input tokens (read×61),
  unsolvable without bash. A *bounded* read-only prefix followed by a bash
  work phase is not the same regime; the read-only data bounds the downside
  (pure reading degenerates into exhaustive file-walks), which is exactly
  what the phase cap must prevent.

**Search-engine ground truth (own search-bench, our corpora):**

| query style | rg hit@1 | sifs bm25 hit@1 | tokens-to-locate |
|---|---|---|---|
| keyword | 0.25–1.00 | 0.67–1.00 | 94–508 |
| natural language | **0.00 everywhere** | **0.50–1.00** | 130–508 |

bm25 is strictly better; rg only matches it when the agent already knows
the exact string (which is just grep). sifs call cost: 4–7ms on small
corpora, ~1.8s per call on a 10k-file corpus (index rebuild per call).

## What the literature says (web, 2026-09-06)

- **Plan-and-Solve** (arXiv 2305.04091, ACL 2023): an explicit plan step
  before execution improves zero-shot multi-step reasoning; became
  LangChain's Plan-and-Execute. Classic support for a dedicated plan step.
- **Industry plan modes** (Claude Code plan mode, Cline Plan&Act, Kiro plan
  mode): the standard is a **read-only exploration phase → plan artifact →
  execution**, with read-only-ness enforced by the **tool surface** (the
  phase's tool list), not by prompt instructions. Kiro/Cline both gate on
  the same two properties: no mutation, and a reviewable plan output.
- **ZEBRA** (arXiv 2605.20485, 4-phase Plan→Decompose→Implement→Refine
  under a fixed budget): zero-shot per-phase budget allocation recovers
  94.4% of unconstrained quality; the coding-optimal split is **skewed to
  refine**, plan gets a modest share; equal splits leave ~5 points on the
  table. Supports: small bounded plan, keep the refine/commit spend.
- **Agentless** (arXiv 2407.01489): a fixed control flow (localize → repair
  → validate) with **no LLM planning** beat interactive agents at a fraction
  of the cost — the plan must not eat the execution budget.
- **Repo notes** (`recon-tool-conversion.md`): planner-executor systems feed
  the planner *summaries, not raw scan output*; nobody pre-runs full recon;
  context discipline is the failure point. `plan-work-review-loop.md`:
  intrinsic reflection is weak, grounded checks win, "when to stop" is the
  unsolved part.

## Design

### Pipeline (new regime value, e.g. `[agent].loop = "v3-plan"`)

```
plan (read-only, fixed caps)  →  main (v3 budget, full tools)  →  commit (on breach)
```

- `plan` reuses `phases/plan.py` machinery (typed `PlanResult`, fresh
  conversation) but with the read-only tool list and its own caps.
- The **v3 budget starts after the plan**: main's wall soft/hard =
  `[v3loop]` values minus plan elapsed wall; `token_budget`/`request_limit`
  minus plan consumption (the plan is small, ~15K fresh tokens). Commit caps
  unchanged (`commit_time_cap` 80s, 25 requests).
- `PlanResult.decision = "commit"` short-circuits main (v5 behaviour — the
  answer is already known and trivial; the commit phase writes and
  verifies the file).
- **Short-task scaling:** `plan_time_cap = min(60s, 0.2 × task_timeout)`.
  120s sanity tasks → ≤24s plan; 300s → 60s; 600s → 60s. (Orientation data
  shows 30–50s covers SOC/seccode; CTF orientation is shorter.)
- Handoff: `MainPhase.prompt` (v3loop.py) prepends the plan summary
  (goal/findings/steps/risks) to the task user message — the template's
  `previous_results` block already exists for the v5 pipeline; for v3 the
  plan text goes directly in front of the task (the main phase is a single
  user message).
- A failed/handoff-error plan **skips to main with no plan** (main degrades
  to plain v3) — never retries (max_retries 0).

### Plan-phase toolset (read-only)

| tool | in plan | why (data) |
|---|---|---|
| `read` | yes | core; 4KB/call cap; SOC orientation = ~3.8 reads |
| `recon` | **yes (baseline)** | ~665ms, ≤8KB; cwe1336: 5 chats/11s vs 8/20s; the web/code/data map replaces the v5 plan's "check the service responds" bash probe |
| `code_search` + `file_outline` | **yes, engine = SIFS bm25** | strictly better engine (bm25 hit@1 0.5–1.0 NL / 0.67–1.0 KW vs rg 0.0 / 0.25–1.0); 1500-token result cap; 4–7ms per call on our corpora |
| `log_triage` | yes | ≤4KB summary of the evidence dir (counts, time ranges, top entities, IOC candidates); SOC pre-work is 3.8 re-reads of the same JSONL files; unused in +forensics only because it was never steered in a free-form bash main |
| `mitre_kb` | yes, on-demand | the **prefix** was the harm (+10.7K fresh tokens/request → 2.2× run cost in the +mitre-kb arm); the on-demand lookup is cheap and the 27 historical calls were reasonable targeted confirmations — in the plan phase they happen *before* the hypothesis instead of after |
| `bash` | **no** | by definition; its only plan-phase use (1.1 calls/run on SOC, cheap probes) is covered by recon |
| `write` / `edit` | **no** | the plan artifact is the typed `PlanResult`, not a file; no scratch notes (the v5 plan's `/tmp` write is dropped for this regime) |

**Zip consequence (decision needed):** the bundled SIFS binary is
**9.3MB** (`agent/tools/bin/sifs`); the current submission zips are ~150KB
without it. Including `code_search(sifs)` in the baseline submission makes
the zip **~9.5MB — under the 10MB cap but with ~0.5MB headroom**. Alternatives:
ship rg instead (no binary, `code_search` over the container's `rg`; but
rg = grep ≈ no added value per the bench), or keep sifs dev-only until a
needle task proves the engine.

### Prompt design

**Tool descriptions stay byte-identical** (they are the pydantic-ai
docstrings, shared across phases); all steering lives in `plan.md` so the
number of prompt variants stays minimal:

```
PLAN PHASE (read-only).
You have read-only tools: recon, log_triage, code_search, file_outline,
mitre_kb, read. You cannot run commands, write files, or start services.
The work phase executes your plan with full tools.

1. Read the task. Extract the exact deliverable spec: file path, format,
   required keys/fields/columns, constraints.
2. Orient FIRST, one call per surface (skip what the task doesn't need):
   - live local target  -> recon(mode="web", target=<url>)   [ports, endpoints,
     sensitive paths, 404 baseline — no service probe needed beyond this]
   - code-fix task      -> recon(mode="code", target=<source dir>)
   - evidence/log task  -> recon(mode="data", target=<dir>) then log_triage
     on the evidence dir; read only the specific lines they flag
   - code tree > ~10 files -> code_search (keyword or natural-language query)
     to locate the file/symbol, then read it
   - reporting a TTP -> mitre_kb to confirm the technique id before you write it
3. At most ~8 tool calls. If the answer is already fully derivable from what
   you read, set decision="commit" — do not pad.

Produce the plan via the final_result tool:
- goal: the exact deliverable spec.
- findings: the key environment facts the plan relies on (paths, values,
  line numbers, entities) — specific enough that the work phase does not
  re-explore to re-derive them.
- steps: ordered actions for the work phase, "action; verify: how to check".
- risks: what could break this plan and the fallback; empty if none.
- decision: "work" (default) or "commit" (answer already known and trivial).
Do NOT write the deliverable file in this phase.
```

**Work-phase addition (one line, regime-gated, appended to main.md or
prepended to the task message):**

```
A read-only plan phase ran before this one; its goal/findings/steps are
above. Execute the steps; do not re-explore what the findings already
establish; if a finding is wrong, adapt once and continue.
```

`recon` also stays in the baseline **work**-phase toolset (the existing
`recon_tool.md` prompt block covers both phases; baseline's work toolset
gains `recon`).

### Budget (initial values, tune from the A/B)

| phase | hard time | soft | requests | tokens (fresh) |
|---|---|---|---|---|
| plan | min(60s, 0.2×T) | 40s | 15 | ~15K soft |
| main | `[v3loop]` minus plan elapsed | 500s−plan | 90−plan | 300K−plan |
| commit | unchanged | — | 25 | `commit_time_cap` 80s |

Rationale: orientation completes in ~5 tool calls (data above); ZEBRA says
plan gets a modest share and the split skews to refine — the commit keeps
its 80s; the plan must never be able to starve the work.

## Implementation sketch

1. `toolsets.py`: baseline toolset gains `recon` (work phase) — or gate on
   regime; decide against the golden-fixture constraint (below).
2. `config.toml`: `[phases.plan] tools = ["read", "recon", "code_search",
   "file_outline", "log_triage", "mitre_kb"]` for the new regime (the v5
   `cycles` plan keeps its current list); new `[v3loop]`-adjacent plan caps
   (or reuse `[phases.plan]` values + the 0.2×T rule in `v3loop.py`).
3. `v3loop.py`: new dispatch `loop = "v3-plan"` — plan first, then the
   current main+commit chain with the budget reduced by plan consumption;
   `MainPhase.prompt` gets the plan summary prepended.
4. `prompts/plan.md`: the read-only variant above (arm/regime-gated like
   the existing recon block); `main.md` unchanged (plan line comes from the
   runner, not the file, to keep `main.md` byte-identical for plain v3).
5. Tests: prompt provenance for the new regime; budget reduction arithmetic
   (plan elapsed wall/tokens subtracted once); plan-failure → plain-v3
   fallback; `decision="commit"` short-circuit; short-task cap (0.2×T).
6. A/B: `shlepa run <preset> --loop v3-plan` vs `--loop v3`, N≥2 per task;
   MLflow per-phase metrics (`tokens_in.plan`, `tokens_in.main`) already
   exist; read digests on whether plan findings were reused by the work
   phase.

## A/B matrix (what to actually run)

| run | plan tools | isolates |
|---|---|---|
| `v3` | — | control (no plan) |
| `v3-plan` | read, recon, log_triage, mitre_kb | plan overhead/benefit with the baseline tools |
| `v3-plan+search` | + code_search, file_outline (sifs) | the engine effect in the plan phase — the experiment the previous search analysis predicted would be decisive only here |
| `v3-plan+rg` (optional) | + code_search (rg) | rg-vs-bm25 head-to-head, now *with* steering |

The +smart-grep/+sifs/+forensics arms retire once the baseline absorbs
recon/search/triage — their tools exist only to be steered, and the plan
phase is the steering.

## Risks / Do NOT

- **Do NOT** expose budget numbers to the model (constraint #63): the plan
  caps are system-side; the prompt says "at most ~8 tool calls", never
  "you have 60s / 15K tokens".
- **Do NOT** add a bash read-only allowlist to the plan phase — +50 lines of
  risk for 1.1 measured pre-work bash calls/run on SOC; recon covers the
  probe need.
- **Do NOT** give the plan phase `write` (not even /tmp): the typed
  `PlanResult` is the artifact; scratch files are state the work phase
  ignores.
- **Do NOT** let the plan wander: the read-only whole-run ablation shows
  unbounded reading degenerates into exhaustive file-walks (66 chats,
  read×61 on smug-dino). Hard time + request cap + the ~8-call line are all
  three load-bearing.
- **Golden fixture:** adding `recon` to the baseline work toolset changes
  the rendered tool list → `tests/fixtures/default_prompt.txt` (test-locked,
  baseline byte-identical) breaks. Options: regime-gate the recon addition
  (fixture untouched) or deliberately regenerate the fixture as part of the
  "recon is now baseline" decision. The user decision 2026-09-06 was
  "recon in baseline" — if it applies to the submitted agent, regenerate
  the fixture deliberately and record it here.
- **Zip:** 9.3MB SIFS binary in the baseline → ~9.5MB submission (fits
  ≤10MB, near-zero headroom). Decide before the next `shlepa zip` (danger
  zone: the 10MB gate).
- **Plan overhead on trivial tasks:** the 120s sanity tasks would lose
  20–24s to planning unless the 0.2×T cap is enforced; the contest
  hello-file class should be measured in the A/B, not assumed free.
- ZEBRA/Snell optimize **known** budgets; our plan caps are a-priori until
  the A/B returns. Treat the initial numbers as priors.

## Sources

- Local: `tmp/trace_runs.json` + `tmp/trace_details.jsonl` (335 v3 runs,
  328 traces, 2026-09-05 batches); `research/code_search/analysis/
  search_bench_20260831-1600.md`; `research/notes/v3loop-regime.md`;
  `research/notes/plan-work-review-loop.md`; `research/notes/
  readonly-tools.md`; `research/notes/recon-tool-conversion.md`;
  `agent/shlepa_agent/{v3loop.py,config.toml,phases/plan.py,
  tools/{recon,log_triage,mitre_kb,code_search}.py,prompts/plan.md}`.
- Web (checked 2026-09-06): Plan-and-Solve (arXiv 2305.04091); Claude Code
  plan mode (read-only exploration + review before execution); Cline Plan &
  Act (docs.cline.bot/core-workflows/plan-and-act); Kiro plan mode
  (kiro.dev/docs/specs/plan); ZEBRA (arXiv 2605.20485); Agentless
  (arXiv 2407.01489).
