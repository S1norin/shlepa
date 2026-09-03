# Read-only Tools for AI Agents (Forensic & Capability-Gating Patterns)

- **Category:** agent-architecture (tooling / forensic tooling)
- **Source:** web research digest (GitHub repos + SANS + arXiv), user request
  2026-09-02, initial candidate list supplied by DeepSeek
- **Reviewed:** 2026-09-02

Research question: what are "read-only tools for AI agents" in the
security/forensics domain, how is read-only-ness enforced, how effective are
they, and which patterns are feasible for Shlepa (offline ACP container,
≤10 MB zip, token-budgeted LLM)?

## Verification of the supplied candidate list

All checked 2026-09-02 against GitHub repos/READMEs. Star counts are as of that
date.

| Tool (DeepSeek name) | Reality | Verdict |
| --- | --- | --- |
| `logflip-sift-agent` | `javierdejesusda/logflip-sift-agent`, 0★, MIT. Real: read-only FastMCP server over a deterministic `logflip` NTFS `$LogFile` timestomp engine; SANS FIND EVIL! hackathon; HMAC-signed audit leaves | Exists, tiny, hackathon-grade. The "0.000 false-positive rate" claim is self-reported, no independent evaluation |
| `evtx-sentinel` | `yaswanthme007/evtx-sentinel`, 0★. Real: six typed read-only tools (evidence registration, Hayabusa/Sigma scan, logon summary, raw-event retrieval, finding verification) + SHA-256 audit log, "enforced at code level, not just prompt" | Exists, tiny. The 39-file / 53-finding / 17-hallucination / 19-min numbers are from its own README (EVTX-ATTACK-SAMPLES set) — self-reported |
| `agentropix-mcp` | `galvangabriel-web/agentropix-mcp`, 0★. Real: "governed" DFIR MCP server wrapping SIFT tools | Exists, tiny; the "16 tools / 7-agent swarm / 2,233 findings" numbers unverified |
| `Agentic-DART` | `Juwon1405/agentic-dart`, 9★, MIT. Real: 48 native + 25 SIFT adapters = **73 typed read-only MCP tools** (README-verified), SHA-256-chained audit, serializer rejects findings without an `audit_id` | Exists, hackathon MVP (June 2026). "30 s / 5–10 min vs days" is self-reported; README only shows a sub-1-minute demo |
| `SysProbe` | no repo matching the described "read-only Windows memory inspection, JSON output"; several unrelated namesakes | **Unverified** — likely hallucinated or renamed |
| `clai` | `IBM/clai` (493★) is a 2023 natural-language→shell project, not a pentest terminal agent with an ask-mode safety gate | Description does not match the name — **conflation** |
| `agent-of-chaos` | no repo found matching "read-only SSH crawl + document" | **Unverified** — likely hallucination |
| `aejo` | no repo found for "autonomous GitHub analyzer" (namesakes unrelated) | **Unverified** — likely hallucination |
| `andriller` | `den4uk/andriller`, 1,601★. Real read-only mobile acquisition (community CE edition) | Exists; a tool, not an agent tool (no LLM) |
| `CloudFox` | `BishopFox/cloudfox`, 2,566★. Real read-only cloud enumeration (AWS/Azure/GCP) | Exists; a tool, not an agent tool |

Papers: "Forensic Traces of AI Agents" is real but misnamed — it is
*"Foundations for Agentic AI Investigations from the Forensic Analysis of
OpenClaw"* (arXiv 2604.05589, KIT); note it is forensics **on** agents
(recovering agent-state traces), not agents doing forensics. **Favia**
(arXiv 2602.12500) is real. The blockchain-agents "read-only analytics"
taxonomy: marginal relevance, dropped. "Awesome-SOAR": real, generic list.

## Own research: the landscape (2026-09-02)

### SANS "Protocol SIFT" is the umbrella

Protocol SIFT (SANS blog, Mar 2026) is SANS's open experimental initiative for
AI-assisted DFIR on SIFT Workstation; it defines the pattern almost all repos
above follow: the AI *directs verified tools and self-corrects; it does not
interpret raw bytes or decide verdicts*. The 2026 FIND EVIL! hackathon produced
the read-only-MCP cohort (logflip, evtx-sentinel, Agentic-DART, trudi,
verdict-dfir).

### Ecosystem beyond the hints (GitHub, checked 2026-09-02)

| repo | ★ | what it is |
| --- | --- | --- |
| `AppliedIR/Valhuntir` (+`sift-mcp`) | 97 | most complete platform: 11 packages, up to 90 MCP tools over 8 backends (forensic-mcp 23, case-mcp 15, windows-triage 13, opencti 8, …), 15 evidence parsers, OpenSearch indexing (17 query tools instead of "consuming billions of tokens reading raw artifacts"), 22K-record forensic RAG, offline Windows baseline (2.6M known-good records), human-in-the-loop examiner portal, full audit trail, LLM-client-agnostic |
| `calebevans/mulder` | 64 | agentic DFIR |
| `nebulae/trudi` | 55 | autonomous DFIR agent, SIFT MCP server |
| `bornpresident/Volatility-MCP-Server` | 39 | Volatility 3 behind MCP |
| `mukul975/Malware-Sandbox-mcp` | 27 | cloud-sandbox detonation / IOC enrichment (not read-only over evidence) |
| `x746b/winforensics-mcp` | 20 | Windows DFIR on Kali |
| `samaritan0/dfir-agentic-suite` | 16 | Claude skill + MCP toolkit |
| `TimothyVang/verdict-dfir` | 12 | signed, offline-verifiable verdicts (Claude Code engine) |
| `0xhackerfren/Pcap-Analysis-MCP` | 9 | PCAP analysis for SOC/DFIR agents |

The most honest statement in the ecosystem (Valhuntir's own README): *"If you
just tell Valhuntir to 'Find Evil' it will more than likely hallucinate… The AI
can accelerate, but the human must guide it and review all decisions."* — this
is the field's actual state, versus the hackathon READMEs'
"hallucination structurally impossible" marketing line (the boundary prevents
*unverifiable* claims, not *wrong-but-verifiable* ones).

### Enforcement: the pattern in four layers

Every credible project separates four boundaries (logflip's README names them):

1. **Tool surface (architectural)** — the MCP server exposes typed read-only
   functions; no write/delete/shell tool exists, so the guarantee lives in the
   surface, not the prompt.
2. **Engine (deterministic)** — verdicts come from a non-LLM engine (logflip's
   4-gate "never-false-confirm", Hayabusa/Sigma, Volatility plugins); the LLM
   reasons over tool outputs.
3. **Verifier/audit (structural or cryptographic)** — HMAC-signed evidence
   leaves, SHA-256-chained audit JSONL, serializers that reject findings
   without an `audit_id`; every finding links to the tool execution that
   derived it (`produced_by_seq` / `corroborated_by_seq`).
4. **Policy (prompt)** — triage heuristics, self-correction protocols
   (four-phase: triage → validate against raw records → correct → report),
   iteration caps, an explicit `UNRESOLVED` state instead of forced verdicts.

Layers 1–3 are what make a design defensible; layer 4 is where model behavior
lives. Academic work corroborates the split: task-conditioned
least-privilege *learning* for terminal+MCP agents (arXiv 2608.18351, Aug
2026) shows static permission gating is insufficient alone — the model must
also *learn* which authority a task needs; reliability work (arXiv
2602.20202) validates LLM-discovered artifacts against a Digital Forensic
Knowledge Graph with deterministic UIDs (13 GB image, 61 apps, 2,864 DBs,
5,870 tables).

### Academic landscape (arXiv, fetched 2026-09-02)

- **OpenClaw forensics** (2604.05589): differential forensic analysis of an
  agent's recoverable traces — forensics *on* agents; context for our own
  telemetry design.
- **SecRespond** (2607.26791): first post-compromise-IR benchmark — forensic
  **disk snapshot + alerts + vuln scans + baselines**, agent with CLI access.
  Closest published analogue to our forensics task shape.
- **STAIR** (2608.09524): end-to-end agentic IR planning with persistent
  incident state and replanning on execution feedback.
- **Digital-twin-validated IR** (2608.15016, 2608.02422): LLM infers the
  attack, a digital twin *validates* the response before execution — the
  machine-oracle pattern from the recon note.
- **Favia** (2602.12500): forensic (commit-level) agent for CVE fix
  identification; notes that random-sampled evaluations "substantially
  underestimate real-world difficulty" (benchmark-hygiene caution).
- **Agentic mobile-DB benchmark** (2608.21470): separates *execution success*
  from *structural correctness* of inferred DB relations — same two-axis
  scoring idea as CCI.
- **Localized AI forensics** (2603.23996): artifact analysis of Ollama /
  LM Studio / llama.cpp traces.

## Fit for Shlepa

Task-side reality (verified 2026-09-02 in `tasks/`): current forensics
evidence is **structured text** — SOC tasks are `*.jsonl` + `*.txt`
(`windows_event_logs.jsonl`, `background_activity.jsonl`, `ticket_context.txt`),
whyos is `console.log` + a `.deb`, the contest task is proxy/auth/app logs.
No `.evtx`, disk images, or memory dumps in the current task set. So the heavy
DFIR stack (Volatility, Plaso, TSK, Hayabusa) is **not needed today** and not
zip-feasible anyway (hundreds of MB vs the 10 MB cap; the ACP image is
offline, no node).

What transfers:

| pattern from the field | fit | feasibility |
| --- | --- | --- |
| **Typed read-only evidence tool** (no shell; structured in → structured findings) | high — forensics + CTF evidence tasks; attacks the token economy (one ≤4 KB summary call vs 20+ grep/read cycles) | **easy**: Shlepa tools are in-process Python functions (`shlepa_agent/tools/`), no MCP runtime needed. A `log_triage` tool (stdlib json/re: timeline spine, entity/IOC extraction, anomaly signals) is ~200–400 lines, KB-scale zip cost, zero new deps. Wired in as a `+forensics` arm via the existing `KNOWN_ARMS`/`apply_arm` pattern (`toolsets.py`) |
| **Per-phase read-only mode** (no write/edit, restricted bash) | medium — contest tasks require a deliverable file, so read-only applies to the plan/explore phase or a dedicated investigation phase; value = auditability + preventing evidence mutation | **easy**: phases already carry explicit `tools = [...]` lists in `config.toml`; an arm swapping the plan phase's list is a one-line config change; a bash read-only command allowlist is ~50 lines |
| **Deterministic engine + LLM interpretation** | high — same insight as the recon-deterministic note (P4/ptai: "methodology, not scale"): the engine finds candidates, the LLM reasons | **medium**: the engine is the new part; start with one schema family (SOC JSONL), add per evidence type |
| **Signed/structured audit trail** | low–medium — MLflow traces already give per-tool-call provenance in dev; the contest does not score auditability | **skip for now**; revisit if a task adds an evidence-integrity requirement |
| **Human-in-the-loop reviewer portal** (Valhuntir) | none — contest runs are fully autonomous | n/a |
| **Read-only cloud/mobile acquisition** (CloudFox, Andriller) | none — no live cloud/mobile targets in the task set | n/a |

**Verdict:** the hinted *tools* are mostly not directly usable — they target
SIFT-appliance evidence (EVTX, disk images) that our tasks don't use, and most
are 0–9★ hackathon code. The *patterns* are usable and cheap: (1) a small
pure-Python read-only triage tool as a new `+forensics` arm, (2) read-only
phase gating through the existing per-phase tool lists. Both are small,
zip-safe, offline-safe, and A/B-testable with `--arm` — the same shape as the
code-search arms already in flight.

### What not to do

- **No MCP server inside the agent**: MCP adds a process/protocol layer for
  zero benefit in a single-process Python agent. The typed-function pattern is
  what matters, not the transport.
- **No SIFT-stack binaries** (vol/plaso/tsk/hayabusa): hundreds of MB, wrong
  evidence type, dead against the 10 MB zip gate.
- **No "hallucination structurally impossible" as a design target**: the
  achievable property is *every finding traceable to a tool output* (the
  `audit_id` property). Valhuntir's own README concedes the model still
  hallucinates without human guidance.

### Implementation sketch (if pursued)

1. `shlepa_agent/tools/log_triage.py` — read-only: takes a JSONL/log path or
   glob, returns compact JSON (counts, timeline spine, top entities, candidate
   IOCs, schema guess) capped at ~4 KB. Stdlib only.
2. `toolsets.py`: add `ARM_FORENSICS = "+forensics"` to `KNOWN_ARMS`;
   `apply_arm` enables the `log_triage` tool and appends it to phase tool
   lists (mirrors the `_enable_search_tools` wiring).
3. A/B: `shlepa run all --arm +forensics` on the forensics families
   (`bench-soc-*`, `bench-ctf-whyos`, `contest-incident-log-forensics`) vs
   baseline, N ≥ 2–3 — same protocol as the code-search A/B.
4. Optional phase gating: a read-only plan phase (`tools = ["read", "bash"]`
   minus write/edit) behind the same arm, to measure the
   auditability/evidence-safety effect.

## Sources

- Protocol SIFT (SANS blog, Mar 2026):
  https://www.sans.org/blog/protocol-sift-experimental-research-initiative-ai-assisted-dfir
- AppliedIR/Valhuntir: https://github.com/AppliedIR/Valhuntir ·
  https://github.com/AppliedIR/sift-mcp
- `javierdejesusda/logflip-sift-agent`:
  https://github.com/javierdejesusda/logflip-sift-agent
- `yaswanthme007/evtx-sentinel`:
  https://github.com/yaswanthme007/evtx-sentinel
- `galvangabriel-web/agentropix-mcp`:
  https://github.com/galvangabriel-web/agentropix-mcp
- `Juwon1405/agentic-dart`: https://github.com/Juwon1405/agentic-dart
- `nebulae/trudi`: https://github.com/nebulae/trudi ·
  `calebevans/mulder`: https://github.com/calebevans/mulder
- `bornpresident/Volatility-MCP-Server`:
  https://github.com/bornpresident/Volatility-MCP-Server
- `x746b/winforensics-mcp`: https://github.com/x746b/winforensics-mcp ·
  `TimothyVang/verdict-dfir`: https://github.com/TimothyVang/verdict-dfir ·
  `0xhackerfren/Pcap-Analysis-MCP`:
  https://github.com/0xhackerfren/Pcap-Analysis-MCP
- `den4uk/andriller`: https://github.com/den4uk/andriller ·
  `BishopFox/cloudfox`: https://github.com/BishopFox/cloudfox
- arXiv: 2604.05589 (OpenClaw), 2607.26791 (SecRespond), 2608.09524 (STAIR),
  2608.15016 & 2608.02422 (digital-twin IR), 2602.12500 (Favia), 2602.20202
  (DFKG reliability), 2608.21470 (agentic mobile-DB), 2608.18351
  (least-privilege), 2603.23996 (localized-AI forensics)
- Internal: `research/notes/recon-deterministic.md`,
  `research/notes/toolsets-modular.md`, `research/code_search/README.md`,
  `agent/shlepa_agent/toolsets.py`, `agent/shlepa_agent/config.toml`,
  `tasks/bench-soc-ntds-vss/environment/evidence/`
