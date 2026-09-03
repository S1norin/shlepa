# Recon as a Tool: Script → Registered Tool for Read-Only Agents

- **Category:** agent-architecture (tooling / reconnaissance)
- **Source:** web research (agent architectures, MCP patterns, benchmarks), user request 2026-09-03
- **Reviewed:** 2026-09-03
- **Supersedes-in-part:** `recon-deterministic.md` (script design), feeds #44, #46, #53

Research question: how should `tools/recon.py` (deterministic attack-surface
mapper, invoked via `bash`) be exposed to the agent — as a **registered tool**,
**pre-run in context**, or hybrid — so that a **read-only agent** (toolset
without `bash`) can still use recon? What do other systems do?

## Motivation

Two gaps in the current design:

1. **Read-only toolsets lose recon entirely.** Recon is a script reachable only
   through `bash`. Any toolset restriction that removes `bash` (the planned
   read-only experiment) deletes the agent's best deterministic recon channel,
   while registered arm tools (`code_search`, `mitre_kb`, `log_triage`) keep
   working — they are self-contained.
2. **Regime inconsistency (bug).** `recon.py` documents an internal wall budget
   of ~100 s "so the run fits the bash tool's 120 s cap", but the v5 bash cap is
   **30 s** (`budget.py::BASH_MAX`, `[tools.bash] max_timeout = 30.0`). Web mode
   (the 100 s internal deadline happily runs past 30 s) is therefore SIGKILLed
   by the bash tool on slow targets — the budget is fiction. Code/data modes
   (fast local scans) survive.

## What other systems do (verified 2026-09-03)

### Architecture landscape (39+ open-source agents, 6 patterns)

Surveyed via AppSec Santa's 2026 technical analysis of 39+ open-source AI
pentesting agents and 8 academic benchmarks:

| pattern | recon exposure | relevance to Shlepa |
|---------|----------------|---------------------|
| single-agent ReAct (PentestGPT, hackingBuddyGPT, AutoPentest) | raw bash/terminal, ad-hoc probes | the "P1" baseline; burns context on discovery |
| planner-executor (VulnBot, CHECKMATE, HPTSA) | planner reads **summaries, not raw scan output**; executors run tools in fresh contexts | supports pre-computed recon context for the plan phase |
| specialized roles (Zen-AI-Pentest, BlacksmithAI) | dedicated **Recon agent** with its own tools, feeds Vuln agent via state | the Shlepa analogue is the *plan phase*; it needs a recon channel |
| dynamic swarm (Pentest Swarm AI, D-CIPHER) | Go swarm wraps subfinder/httpx/nuclei/naabu/katana/dnsx/gau natively | confirms the standard recon stack; binaries do not fit our zip (see `recon-deterministic.md`) |
| **MCP-based** (HexStrike 150+ tools, AutoPentest-AI 68+, PentestMCP) | **classical scanners exposed as typed endpoints with typed I/O schemas; the model orchestrates them itself** | the strongest precedent for "recon as a registered tool with a fixed schema" |
| Claude Code native (Raptor, Transilience, Claude Bug Bounty) | markdown skill files configure the built-in runtime; Transilience 100% on a CTF benchmark | prompt-as-config is already our model (`prompts/*.md` + template blocks) |

### Convergence points

1. **Recon is always phase 1, and the tool chain is nearly identical
   everywhere:** subfinder → httpx → nmap → fingerprint → (nuclei). Our
   `recon.py` web mode implements exactly this pipeline in-process (ports →
   base probe → vhosts → endpoints → sensitive paths) — it is the deterministic
   core the survey says every system needs, just without external binaries.
2. **Typed tools over raw command strings.** The MCP pattern (and CHECKMATE's
   classical-planning "modular actions") both arrive at the same design:
   *predefine the execution details of specialized tools in code so the LLM
   never iterates to refine simple commands on the fly*. A registered `recon`
   tool with a fixed `mode`/`target` schema is exactly this — the model picks
   the target, the engine owns the probe plan.
3. **Context discipline is the failure point.** Single-agent systems die when
   "a single nmap scan can spit out thousands of lines and push earlier
   findings out of context". The fixes are (a) compact deterministic output
   (our 8 KB JSON contract) and (b) feeding planners *summaries, not raw
   output* — i.e. recon results injected as context for the plan phase.
4. **Terminal-only is a deliberate experimental extreme, not the norm.**
   Cybench restricts agents to a **bash-only** Kali environment (the model
   drives classical tools itself). The read-only (no-bash) experiment is the
   complement: it measures how much of the model's recon value comes from
   driving tools vs. consuming pre-computed surface maps. This is the whole
   point of making recon a tool — the read-only arm isolates the model's
   reasoning while recon stays available.
5. **Failure mode to avoid:** EnIGMA (ICML 2025) "soliloquizing" — agents stop
   running commands and imagine the output. Deterministic tool output (fixed
   probe plan, fail-safe sections, capped JSON) is the structural mitigation.
6. **Nobody pre-runs full recon before the loop.** No surveyed system fires the
   complete recon pipeline at episode start; recon is either a dedicated phase
   (specialized recon agent) or on-demand tool calls. Pre-computation appears
   only as *cheap summaries* for planners (planner-executor pattern). So a
   full pre-run is not a proven pattern; a *cheap, cheap-to-skip* pre-run is
   the defensible variant.

## Options for Shlepa

### Option A — registered tool `recon` (recommended, now)

Refactor `tools/recon.py` into an importable in-package engine
(`shlepa_agent/recon.py`) and expose a registered tool
(`recon(mode, target)`; `mode = web|code|data`):

- engine runs in-process (stdlib only, no binaries → no zip growth), worker
  thread under the standard 30 s per-call wall (`asyncio.timeout`), internal
  deadline ~25 s so the JSON completes *before* the wall (fixes gap 2);
- output = same 8 KB fail-safe JSON, wrapped in `UNTRUSTED TEXT` markers
  (environment data);
- toolset arms: `+recon` (baseline + tool) and `read-only`
  (read/write/edit + recon, **no bash**) — the read-only arm is the
  experiment that proves the requirement;
- prompt: the `RECON SCRIPT` section of `base.md` moves to its own template
  block with two variants — tool instructions when the tool is enabled,
  script instructions otherwise (baseline byte-identical, golden fixture).

Properties: works in **any** toolset (bash or not), one A/B variable per arm
(toolsets-modular rule), zero new dependencies, fixes the deadline bug.

### Option B — pre-run in context (not recommended standalone)

Runner auto-detects the target (URL/path from the task prompt), runs recon
before plan, injects the JSON into the plan context as a `recon` template
block.

- pros: zero model decisions; recon available even with a *minimal* toolset;
  deterministic per task.
- cons: target extraction from prompt text is heuristic (URLs, relative
  paths, "the service at 9000" phrasings); pays ~2 K tokens + up to 30 s
  latency on *every* run including non-recon tasks; cannot follow up (new
  targets discovered mid-run need a channel — back to a tool); no surveyed
  system does full pre-runs (see convergence point 6).

### Option C — hybrid (tool + cheap pre-run, later)

Option A plus an opt-in pre-run for the **plan phase only**, gated on a
high-confidence target extraction (explicit `http(s)://` or `host:port`
in the prompt; never heuristic guesses), off by default, config/dev knob.
Revisit only if A/B shows the model fails to call the tool on live-target
tasks (the #44/#53 data will answer that).

## Recommendation

1. **Now (plan):** Option A — engine refactor + deadline fix + `recon` tool +
   `+recon` and `read-only` arms + docs. Small, testable, baseline-invariant.
2. **Deferred (explicitly not now):** A/B validation — `baseline` vs `+recon`
   vs `read-only` on live-target tasks (`bench-ctf-smug-dino`,
   `bench-cve-bench-cve-2024-2771` once merged) plus code/data tasks;
   N=2–3 repeats, `toolset` tag, compare solved/tokens/duration/tool_calls,
   digest read for tool consumption. This also discharges the pending A/B of
   #44 and the first A/B of #53. Option C is a follow-up issue, conditional on
   the A/B results.

## Constraints / danger zones

- Baseline golden fixture (`tests/fixtures/default_prompt.txt`) must stay
  byte-identical; all prompt changes are arm-gated.
- `agent/agent.py` untouched; no new core dependencies (stdlib only);
  zip stays ≤ 10 MB (no binaries added).
- UNTRUSTED markers on recon output (it is environment data, including in the
  read-only arm).
- A/B batches are GPU/endpoint-bound — user approval required before running.

## Sources

- AppSec Santa, "The Rise of AI Pentesting Agents: A Technical Analysis (2026)",
  appsecsanta.com/research/ai-pentesting-agents-2026 (6 patterns, tool chains,
  MCP landscape, Cybench context).
- Wang et al., "Automated Penetration Testing with LLM Agents and Classical
  Planning" (PEP paradigm, CHECKMATE, Vulhub eval),
  arxiv.org/html/2512.11143v1.
- Cybench (cybench.github.io; Khan et al. 2024) — bash-only agent environment;
  40 CTF tasks; used in AISI/Anthropic/Google model evaluations.
- AutoPenBench, arxiv.org/abs/2410.03225 — fully autonomous vs assisted agent
  SR gap (21% vs 64%) — context for what tooling removes from the model.
- Local: `research/notes/recon-deterministic.md` (script design, binary
  reality, P1 evidence), `research/notes/toolsets-modular.md` (arm design,
  A/B methodology), `agent/tools/recon.py` (current implementation).

## Re-verification (2026-09-03, plan recreation)

- **Base branch corrected:** the recon work branches from `feature/kb-expansion-wire`
  (8d35508: 5-arm toolsets + `mitre_kb`/`log_triage` engines, not yet merged into
  dev), not from `dev` (6e91953: 3-arm toolsets, no engines). The earlier
  "511-line vs 884-line branch discrepancy" was a misread: `recon.py` is a single
  ~884-line version on all branches (added in `b43e01d`, flake8-fixed in
  `7215dc1`), with entry functions `recon_web` / `recon_code` / `recon_data`
  (not `run_*`). Engine module: `shlepa_agent/recon.py` must expose those
  existing names to minimize diff and keep parity testing trivial.
- **Fresh sources (2026-09-03, session 2):**
  - Aider repo map (aider.chat/docs/repomap.html) — the canonical
    pre-computed deterministic context pattern (tree-sitter symbols + graph
    ranking, map sent with each request). Confirms Option C's shape:
    pre-computation is valid only as a *cheap injected summary*, not a full
    pipeline pre-run.
  - HexStrike AI MCP (github.com/0x4m4/hexstrike-ai) — 150+ security tools as
    typed MCP endpoints, model-orchestrated; re-confirms the Option A
    typed-tool precedent.
  - Cybench (cybench.github.io) — bash-only agent environment; the read-only
    arm is its deliberate complement (see convergence point 4).
