# Deterministic Reconnaissance for the Agent

- **Category:** agent-architecture (tooling / reconnaissance)
- **Source:** web research digest (tools + 2024–26 papers), user request 2026-08-30
- **Reviewed:** 2026-08-30

Research question: what small, **deterministic** reconnaissance approach fits
Shlepa — something that does not rely on the LLM agent to drive discovery — and
how hard is it to implement?

## Motivation

On live-target tasks (web CTF, running vulnerable apps), the agent today is a
"P1-style" agent: it discovers the attack surface with dozens of ad-hoc
`curl`/`grep` tool calls, each consuming up to 16 KB of context. That burns the
token budget on *discovery* instead of *exploitation*. The literature and 2025–26
tooling converge on the same answer: a **deterministic pipeline does the
recon; the LLM only interprets and exploits**.

## Methods of different tools

All verified 2026-08-30 against primary sources (repos/docs).

### Hybrid "deterministic pipeline + surgical AI" tools

| tool | what it is | deterministic core | AI role |
|------|-----------|--------------------|---------|
| [aiscan](https://github.com/chainreactors/aiscan) (chainreactors, AGPL) | single-Go-binary pentest agent, 3 modes | `scan` = auto-chained pipeline: port discovery (gogo) → web probe/fingerprint (spray) → weak creds (zombie) → POC (neutron) → secrets (proton); no LLM needed | `agent` mode: 160-line loop over the same engines; optional AI verification of scan results |
| [RedAmon](https://github.com/wakuseo/waku-redamon) | containerized pentest framework (Kali + Neo4j + LangGraph) | 6-phase recon pipeline: subdomains (crt.sh/CT, passive APIs, brute) → Naabu ports → httpx+Wappalyzer fingerprint → katana/GAU/kiterunner endpoints → Nuclei → MITRE enrichment; single JSON + graph output | LangGraph orchestrator *queries the graph before every decision*; AI in scoped doses, pipeline continues on AI failure (exact "never raise" wording: unverified) |
| [Vigolium](https://docs.vigolium.com) | web vulnerability scanner, Go | `vigolium scan` = deterministic multi-phase pipeline | `vigolium agent` = agentic audit; token/time budget caps |
| [ptai](https://github.com/0xSteph/pentest-ai) (0xSteph) | AI pentester CLI + MCP server | curated deterministic probe library; `--no-llm` runs the identical 18-phase tool loop; **a finding is "candidate" until a named machine oracle re-runs the exploit N/N times** ("no LLM ever produces a verdict" — enforced in code) | LLM only coordinates phases and reasons about results |
| [P4 Deterministic-Hybrid / ARG](https://arxiv.org/abs/2605.23243) (paper architecture) | Agentic Reasoning Graph, 18 parallel vuln-family agents | predefined graph nodes do test generation, request execution, evidence comparison, **confirmation**; "deterministic classification that cannot hallucinate"; runs with model-native capabilities only (bash/HTTP/file I/O) | LLM-driven reconnaissance + payload generation feeding deterministic nodes |
| [LLM-Guided-Crawler-Secret-Hunter](https://github.com/SSDEVIL108/LLM-Guided-Crawler-Secret-Hunter) (tiny, Python) | bug-bounty recon | recursive crawl with deterministic (BeautifulSoup) extraction of links/JS — "0% hallucination extraction" | parallel multi-model LLM audit of the extracted code only |
| [HTTPS Finder](https://github.com/bolbolabadi/https-finder) (tiny, Python) | internal-net recon | multithreaded nmap+httpx pipeline | none |
| [SScanner](https://github.com/Unknownx007/SScanner) (tiny) | local infra scans | background Nmap/Subfinder/Dirsearch threads, local logging | optional AI analysis of packaged results |

### Convergence pattern

Every one of these (and the classic projectdiscovery stack they embed) uses the
same deterministic core:

1. **ports/services** — top-N scan, banner grab
2. **HTTP probing** — status, title, headers, content-type, TLS/cert
3. **tech fingerprint** — server / x-powered-by / generator-meta / JS-library signatures
4. **endpoint discovery** — BFS crawl (depth 1–2) + wordlist path brute + JS link/param extraction
5. *(optional)* template/POC pass (Nuclei, 8k+ templates) — the only stage with big assets

Plus two engineering contracts worth copying: **fail-safe** (every stage emits
something even on error; one bad target never kills the run; per-stage timeouts)
and **deterministic confirmation** (probes find candidates; a fixed oracle
re-runs them; the LLM never certifies a finding).

### Binary reality (linux amd64, latest releases, 2026-08-30)

| tool | size | fits 10MB zip? |
|------|------|----------------|
| ffuf v2.2.1 | 4.1 MB | yes (only one that does) |
| subfinder v2.16.0 | 10.0 MB | no (and its internet OSINT modes are useless offline) |
| naabu v2.6.1 | 11.9 MB | no |
| httpx v1.10.0 | 19.1 MB | no |
| katana v1.7.0 | 31.7 MB | no |
| aiscan std v1.0.0-rc2 | 30.1 MB (full 57.3) | no |
| nuclei v3.11.1 | 46.1 MB (+ ~1GB templates) | no |

Our submission zip is currently **11.5 KB**, so bundling *scripts* is free and
bundling *ffuf* is possible; everything else from the prebuilt ecosystem is over
cap. `secureintelligent/acp:latest` ships python3.12 + `requests` + `httpx`
(client) + curl + jq but **no nmap/ffuf/naabu**, so a stdlib/requests script has
zero new dependencies while any external binary needs packaging work.

## Results compared to baseline

- **Dual-Mode Vulnerability Benchmarks** ([arXiv 2605.23243](https://arxiv.org/abs/2605.23243),
  2026; 5 production-style web apps, 118 ground-truth vulns, 6 frontier models):
  black-box coverage **4–8%** for direct prompting (native bash/HTTP, no
  methodology) → **10–19%** with external security tools (Playwright MCP, Burp
  MCP) → **>50% per vulnerability family** with structured methodology
  (P3 agentic, P4 deterministic-hybrid). Their framing: *"methodology, not scale,
  is the primary lever."* Notably P4 uses **no external tools** and still wins —
  deterministic structure beats tool access.
- **TermiBench** ([arXiv 2509.09207](https://arxiv.org/abs/2509.09207)): 510
  hosts / 25 services / 30 CVEs; realistic settings "require autonomous
  reconnaissance, discrimination between benign and exploitable services";
  finding: existing systems **hardly obtain system shells** under realistic
  conditions — recon-level service discrimination is a named failure mode.
- **AutoPenBench** ([arXiv 2410.03225](https://arxiv.org/abs/2410.03225),
  [code](https://github.com/lucagioacchini/auto-pen-bench)): 33 attack tasks;
  generative-agent pentest benchmark; consistent with the "far below human"
  regime across the field.
- **ptai** (practitioner numbers): fully autonomous LLM agents finish **21–31%**
  of pentest tasks end-to-end vs **64%** human-assisted; the design answer is a
  deterministic probe library + machine oracles, LLM only coordinates.
- **ethibench** ([arXiv 2605.10834](https://arxiv.org/abs/2605.10834)): protocol
  for scoring agents by *validated* vulnerability discovery on complex targets
  (context for measuring recon-heavy work).
- Caveat: no head-to-head of "agent + recon script" vs "agent alone" was found
  in the literature; the deltas above are per-paradigm, not per-tool. A
  local A/B (below) is the missing piece and is cheap to run.
- Misapplied in secondary sources: **"Know Your Agent"** ([arXiv 2607.19837](https://arxiv.org/abs/2607.19837))
  is real, but it is reconnaissance-driven pentesting *of AI agents* (defensive
  red-teaming), not a recon tool for offensive tasks.

## Fit for Shlepa

**Task families that benefit** (live local targets): `bench-ctf-smug-dino`
(flag in a misconfigured nginx vhost — needs vhost/path probing, on
`feature/bench-ctf-subset`), `bench-cve-bench-cve-2024-2771` (WordPress
privilege escalation on a live instance — needs WP/plugin fingerprint +
`xmlrpc.php`/`wp-json` discovery, on `feature/bench-cve-bench`), and future
local-service contest tasks (e.g. an `contest-insecure-api-app` variant run as a
service). **No benefit**: seccodebench / socbench / whyos / contest codefix &
vuln-find (source or logs are given), sanity.

**Constraints check** (all verified on the acp image): python3.12 + requests +
httpx preinstalled → a stdlib/requests recon script adds **zero dependencies**
and ~20–30 KB to an 11.5 KB zip. Bash tool cap is 120 s → top-100-ports scan +
~100 threaded path probes on a localhost target finish in a few seconds.

**The win is token economy, not detection power**: one `recon.py URL` call
returns a ≤3 KB JSON attack-surface summary (open ports, service fingerprints,
tech stack, discovered endpoints, obvious hints) replacing 20–40 exploratory
tool calls. The system prompt already orders the agent to "explore only what is
required"; recon.py is the deterministic implementation of that rule for live
targets, and its deterministic confirmation-friendly output (signals, not
verdicts) matches the P4/ptai anti-hallucination pattern.

## How hard to implement

Scope: one bundled `tools/recon.py` (~300–500 lines stdlib+requests) with the
4-stage core (ports → probe/fingerprint → endpoints → hints), a small wordlist
(a few KB), per-stage timeouts (hard ~90 s), strict fail-safe (every stage emits
a section even on error), JSON output with per-field char caps; one system-prompt
line ("for live targets, run `python3 tools/recon.py <url>` first and read its
JSON"). No new image layers, no zip growth worth noting, no LLM calls inside.

Effort: **~2–3 dev-days** including a local fixture server for unit tests.
Compared to prior work recorded in this repo (agent v1 port — 898-line core;
OTel/MLflow telemetry stack; Harbor task adaptation) this is **smaller than any
prior feature**, comparable to a single `shlepa` CLI subcommand.

Validation (infrastructure already exists): A/B `shlepa run` batches with and
without the script on `bench-ctf-smug-dino` + `bench-cve-bench-cve-2771`;
compare `solved`, `tokens_total`, `duration_sec` from MLflow metrics; inspect
digests for whether the agent actually consumed the recon output.

## Recommendation

- **Build (small):** bundle the zero-dependency deterministic recon script
  described above; steal the *pattern* from aiscan/ptai/P4, not their code
  (all are 3× over the zip cap or framework-scale).
- **Defer:** bundling `ffuf` (4 MB, fits) or nmap — only if a task proves the
  built-in wordlist brute is the bottleneck.
- **Reject for now:** adopting aiscan/Vigolium/RedAmon as a whole, or Nuclei
  templates (46 MB + 1 GB assets; single-app targets don't need an enterprise
  attack-surface pipeline).
- **Track:** convert this note's "build" item into a GitHub issue via the
  `backlog` skill when picked up.

## Sources

- aiscan: https://github.com/chainreactors/aiscan (README, v1.0.0-rc2 releases)
- RedAmon: https://github.com/wakuseo/waku-redamon (README, recon-pipeline section);
  wiki: https://github.com/samugit83/redamon/wiki/Recon-Pipeline-Workflow
- Vigolium: https://docs.vigolium.com/getting-started/native-scan
- ptai: https://github.com/0xSteph/pentest-ai (README); subagents:
  https://github.com/0xSteph/pentest-ai-agents
- LLM-Guided-Crawler-Secret-Hunter:
  https://github.com/SSDEVIL108/LLM-Guided-Crawler-Secret-Hunter
- HTTPS Finder: https://github.com/bolbolabadi/https-finder
- SScanner: https://github.com/Unknownx007/SScanner
- P4/Dual-Mode paper: https://arxiv.org/abs/2605.23243
- TermiBench: https://arxiv.org/abs/2509.09207
- AutoPenBench: https://arxiv.org/abs/2410.03225 · https://github.com/lucagioacchini/auto-pen-bench
- ethibench: https://arxiv.org/abs/2605.10834
- Know Your Agent (defense context only): https://arxiv.org/abs/2607.19837
- Unverified: RedAmon's "never raise, always fall back" exact wording (design is
  consistent with it, phrase not found in README); masscan release size (no
  standard releases via API).
