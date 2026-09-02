# Modular Tool Systems and Tool-Set Comparison for Shlepa

- **Category:** agent-architecture (tooling / experimentation)
- **Source:** deep web search + arXiv API, user request 2026-08-30
- **Reviewed:** 2026-08-30

Research question: should the agent's tool layer be modular (named,
selectable combinations of tools), and what does the literature say about
comparing tool combinations? This is the design basis for the toolset
feature requested by the user (A/B different tool combinations per
`shlepa run` batch).

## What "DeepSeek research" turned out to be

Verified 2026-08-30: there is **no DeepSeek publication on modular tool
systems for security agents**. What exists on the DeepSeek side:

- DeepSeek-R1-0528 release notes (deepseek.com/en/news/r1-0528): added
  JSON output **and function calling** to the API — relevant only as a
  capability fact (the model can do function calling reliably enough that
  a fixed tool schema is a stable interface).
- No DeepSeek paper on tool selection, tool ablation, or toolset design
  was found (checked arXiv API + search engines 2026-08-30).

The literature anchors that actually support the feature:

## Findings

### Tool layer = first-class experimental variable (the core argument)

- **SWE-agent** ([arXiv 2405.15793](https://arxiv.org/abs/2405.15793),
  Princeton, "Agent-Computer Interfaces Enable Automated Software
  Engineering"): the central claim is that the **ACI — the design of the
  tools and how the model interacts with the computer — is a primary
  determinant of agent success**, on par with model choice. Their ablations
  show large success deltas from adding/removing a single specialized tool
  (e.g. the file viewer) and from interface choices like agentic search
  (`<SEARCH>` tokens) vs raw file dumps. Consequence for us: the tool set
  is not plumbing; it is an experiment knob that must be swappable and
  comparable per batch.
- **Cybench** ([arXiv 2408.08926](https://arxiv.org/abs/2408.08926), UIUC,
  "A Framework for Evaluating Cybersecurity Capabilities and Risks of
  Language Models"): 40 pro-level CTF tasks + subtask scoring; the
  reference cybersecurity agent is deliberately a *small fixed tool set*
  (shell execution + code interpreter) — evidence that even at the
  frontier, security agents are evaluated with minimal tool surfaces, and
  that per-tool ablations are the standard way to attribute deltas.

### Tool-set size is measurable, not vibes

- **How Many Tools Should an LLM Agent See? A Chance-Corrected Answer**
  ([arXiv 2605.24660](https://arxiv.org/abs/2605.24660), 2026-05): treats
  the *number of tools shown* as the evaluation object. Show too many and
  the model struggles to pick; too few and the right one is absent. Uses
  Bits-over-Random (chance-corrected success) across registries of 20–3,251
  tools; the random baseline rises with list length, so "more tools" is
  penalized by construction. Practical reading for Shlepa: with 5–10 tools
  we are far below overload, but A/B comparisons must control for the fact
  that a bigger tool set has a higher random-use floor — compare on
  *task outcome + token cost*, not on tool-call count alone.
- **AutoTool** ([arXiv 2511.14650](https://arxiv.org/abs/2511.14650),
  2025-11): observes *tool usage inertia* (tool calls follow predictable
  sequences) and cuts inference cost ~30% by predicting the next tool
  instead of re-querying the LLM. Dynamic per-step tool selection is a
  **future** direction, not a v1 requirement — a fixed, named tool set per
  batch is the right granularity now.

### What this implies for Shlepa

- Today the tool layer is hardcoded: five `@agent.tool` closures in
  `agent/shlepa_agent/core.py` (`bash`, `read_file`, `write_file`,
  `append_file`, `apply_diff`) plus a hardcoded "Tools:" prompt line and a
  hardcoded LIVE TARGETS block pointing at `tools/recon.py`. Nothing can be
  A/B'd without editing `core.py`.
- The pending recon A/B (issue #44: "Integrate recon.py into agent
  protocol + A/B validation") is the **first concrete consumer** of the
  toolset feature: the two arms are exactly "baseline toolset" vs
  "baseline + recon prompt module".
- Comparison infra already exists: per-run MLflow metrics
  (`solved`, `tokens_total`, `duration_sec`, `tool_calls`) + `batch_id`
  tag + `trace-export`. What is missing is (a) a swappable tool layer,
  (b) a per-run `toolset` tag, (c) a preset/CLI knob.
- Methodology caveat (from the tool-count paper): LLMs are non-deterministic
  at our temperatures — A/B arms need **N≥2–3 repeats per arm** on the same
  model/endpoint/tasks before trusting a delta; one-off runs are
  indicative only.

## Design sketch (matches the repo's existing conventions)

1. **Registry** (`agent/shlepa_agent/toolsets.py`): each tool =
   `(name, prompt_line, async fn, optional prompt sections)`. Named
   toolsets: `baseline` (the current five, byte-identical prompt),
   `recon-prompt` (baseline + LIVE TARGETS block — the recon script is
   already bundled in the zip, the module only toggles the instruction),
   plus candidate arms like `bash-only` for token-economy experiments.
   pydantic-ai 2.35.0's `agent.tool(fn)` accepts direct calls, so a
   registry loop is the whole mechanism.
2. **Selection**: `AGENT_TOOLSET` env var (default `baseline`), same
   pattern as the existing `AGENT_*` config vars; unknown spec → log
   `toolset_invalid`, fall back to baseline (the agent never crashes).
3. **Experiment plumbing**: `experiments/*.yaml` gains a `toolset:` field;
   `shlepa run [preset] --toolset X` overrides; the MLflow run is tagged
   `toolset=<spec>` alongside `model`/`preset` — comparison is then just a
   tag-scoped MLflow query (no new UI).
4. **Invariant**: with the env var unset, behavior (prompt bytes, tool
   list, logs) is identical to today's submission — the regression gate.

## Fit for Shlepa

- **Effort:** registry + prompt generation + env wiring ≈ 1–2 dev-days
  (smaller than the recon script itself); CLI/preset/MLflow tag ≈ 0.5 day;
  docs + first A/B ≈ 0.5 day + run time.
- **First arms to compare:** `baseline` vs `recon-prompt` on the
  live-target tasks (`bench-ctf-smug-dino`, `bench-cve-bench-cve-2024-2771`)
  — directly answers #44. Later arms: `bash-only` (does the LLM need file
  tools at all given bash?), per-tool removals à la SWE-agent ablations.
- **Constraints:** no new deps (stdlib + existing pydantic-ai); `agent.py`
  stays byte-identical; submission zip ≤10 MB unaffected (the module is a
  few KB inside the package).

## Recommendation

- **Build:** the modular registry + named toolsets + `AGENT_TOOLSET` +
  preset/CLI/MLflow-tag plumbing (issues filed from this note).
- **Then:** run the `baseline` vs `recon-prompt` A/B (unblocks #44) before
  adding further arms — pick the next arm from what the traces show.
- **Defer:** dynamic per-step tool selection (AutoTool-style), tool
  retrieval from large registries (irrelevant at <20 tools), MCP-style
  tool loading.

## Sources

- SWE-agent: https://arxiv.org/abs/2405.15793 (v3, 2024-05)
- Cybench: https://arxiv.org/abs/2408.08926 (v4, 2024)
- Tool shortlist size: https://arxiv.org/abs/2605.24660 (2026-05)
- AutoTool: https://arxiv.org/abs/2511.14650 (2025-11)
- DeepSeek-R1-0528 (function calling capability only):
  https://www.deepseek.com/en/news/r1-0528/
- Internal: `research/notes/recon-deterministic.md` (A/B methodology),
  issue #44 (recon A/B), `agent/shlepa_agent/core.py` (current tool layer).
