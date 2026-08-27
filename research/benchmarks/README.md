# Security agent benchmarks

Research on external benchmarks relevant to Shlepa (a security agent for the
Universal Agent Competition). **Master index below** — one row per
benchmark; full digests in [`notes/`](notes/), PDFs in
[`papers/`](papers/), cross-cutting analysis in [`analysis/`](analysis/).

Conventions for this directory: [`../README.md`](../README.md).

**Pillar key** (evaluation framing from the source discussion):
`C` = cybersecurity competence · `A` = agent competence (tools, state,
multi-step) · `S` = security of the agent itself (injection/robustness).

## Index

### CTF / offensive

| benchmark | pillars | what it tests (one line) | env / offline? | Shlepa fit | note |
| --------- | ------- | ------------------------ | -------------- | ---------- | ---- |
| [CrackMeBench](notes/crackmebench.md) | C+A | CrackMe RE: recover validation logic, produce accepted input | no-network Linux Docker, 5-min budget | **adapt 3–4 tasks first** — matches our env exactly | [notes](notes/crackmebench.md) |
| [CTFTiny + CTFJudge](notes/ctftiny.md) | C+A | 50 cross-category CTF challenges; CCI partial credit on trajectories | Docker challenges | **top "proving ground"**; steal CCI trajectory scoring | [notes](notes/ctftiny.md) |
| [NYU CTF Bench](notes/nyu-ctf-bench.md) | C+A | 200 validated challenges (CSAW 2011–23), prebuilt Docker images | Docker + Docker Hub images | **top adaptation candidate** — closest structure to Harbor | [notes](notes/nyu-ctf-bench.md) |
| [Cybench (NVIDIA)](notes/cybench.md) | C | 40 professional CTF tasks, 6 categories, subtask gradation | Kali container + optional servers | good single-task source; **watch BountyBench** (vuln find/exploit/patch) | [notes](notes/cybench.md) |
| [DeepRed](notes/deepred.md) | C+A | 10 VM-based CTF challenges, attacker-VM topology | Kali VM + target VM, private network | borrow **partial-credit checkpoints**; adapt 1–2 | [notes](notes/deepred.md) |
| [ExploitBench](notes/exploitbench.md) | C | 41 V8 N-day bugs, 16-flag capability ladder to ACE | per-bug containers, 300-turn budget | **skip as eval**; steal capability-ladder + deterministic oracle design | [notes](notes/exploitbench.md) |
| [AgentRE-Bench](notes/agentre-bench.md) | A | long-horizon RE on synthetic binaries, 25-tool-call budget | local binaries + static tools, Linux+Windows | adapt a few levels as agent-capability probes | [notes](notes/agentre-bench.md) |
| [CyberGym](notes/cybergym.md) | C | 1,507 real vulns / 188 repos: description → reproducing PoC | per-instance containers (ARVO), large storage | **port a small subset** (3–5 instances) | [notes](notes/cybergym.md) |

### Vulnerability exploit / fix

| benchmark | pillars | what it tests (one line) | env / offline? | Shlepa fit | note |
| --------- | ------- | ------------------------ | -------------- | ---------- | ---- |
| [SecCodeBench-V2](notes/seccodebench.md) | C (fix) | 98 secure generation/fix scenarios, 22 CWEs, functional+security PoC tests | plain code + tests | **first-priority adaptation** — exactly the fix-sqli contract | [notes](notes/seccodebench.md) |
| [SEC-bench / SEC-bench Pro](notes/sec-bench.md) | C | PoC generation + patching on auto-generated vuln repos; Pro: 344 real engine/kernel bugs | isolated containers, $0.87/instance | **task factory** for find/fix pairs; study gold-patch eval | [notes](notes/sec-bench.md) |
| [CVE-Bench](notes/cve-bench.md) | C | exploit 40 critical web-app CVEs (zero-day/one-day) | Docker targets + network | adapt 1–2 as "demonstrate the vuln" tasks | [notes](notes/cve-bench.md) |
| [SWE-bench](notes/swe-bench.md) | A | resolve real GitHub issues, hidden-test verification | per-task repo containers | keep the hidden-test verifier pattern; optional probes. **VulnAgentBench (source list) unverified** | [notes](notes/swe-bench.md) |
| [3CB](notes/3cb.md) | C | 15 MITRE ATT&CK-aligned offense challenges, robust elicitation | sandboxed Docker targets | threat-model reference; low priority | [notes](notes/3cb.md) |

### SOC / defensive

| benchmark | pillars | what it tests (one line) | env / offline? | Shlepa fit | note |
| --------- | ------- | ------------------------ | -------------- | ---------- | ---- |
| [SOCBench](notes/socbench.md) | C+A | 55 attack scenarios, raw telemetry → JSON investigation + Sigma rule | containerized SIEM stack (ES/Kibana, LocalStack) | **mine 2–3 scenarios** for forensics-family tasks; verdict taxonomy (TP/FP/benign) | [notes](notes/socbench.md) |
| [CyberSOCEval (CSE4)](notes/cybersoceval.md) | C | malware analysis + CTI reasoning (Meta, part of CyberSecEval 4) | data-centric, offline | knowledge baseline; "test-time scaling doesn't transfer" finding | [notes](notes/cybersoceval.md) |
| [CTI-REALM](notes/cti-realm.md) | C+A | CTI → detection rules; emulated attacks on Linux/cloud/AKS; **trajectory reward** | analyst env + emulated attack traffic | **steal two-part scoring** (final + trajectory); don't port | [notes](notes/cti-realm.md) |
| SecMind | — | **UNVERIFIED** — no paper/repo/dataset found | — | treat as hallucinated reference | [notes](notes/secmind-unverified.md) |

### Agent security (self-security)

| benchmark | pillars | what it tests (one line) | env / offline? | Shlepa fit | note |
| --------- | ------- | ------------------------ | -------------- | ---------- | ---- |
| [AgentDojo](notes/agentdojo.md) | S | 97 tool tasks + 629 injection test cases; utility × ASR | local package, simulated backends | **top agent-security reference**; injection-laden task variants, utility×ASR reporting | [notes](notes/agentdojo.md) |
| [InjecAgent](notes/injecagent.md) | S | 1,054 IPI cases: 17 user tools × 62 attacker tools | local harness | recipe for injection variants of our tasks | [notes](notes/injecagent.md) |
| [ASB (Agent Security Bench)](notes/asb.md) | S | 10 scenarios, memory poisoning, PoT backdoor, 11 defenses | scenario sandboxes | threat-model catalog (attack-stage taxonomy) | [notes](notes/asb.md) |

### Knowledge / general

| benchmark | pillars | what it tests (one line) | env / offline? | Shlepa fit | note |
| --------- | ------- | ------------------------ | -------------- | ---------- | ---- |
| [CyberSecEval 2/3](notes/cyberseceval.md) | S+C | risk suites: prompt injection, code-interpreter abuse, **FRR** tradeoff | prompt-based, offline | model-swap sanity screen; steal FRR for our adversarial variants | [notes](notes/cyberseceval.md) |
| [RedSage / RedSage-Bench](notes/redsage.md) | C (knowledge) | 30K MCQ + 240 open QA; local 4B-class cyber LLM recipe | static QA | model-selection screen; **local-model post-training recipe** | [notes](notes/redsage.md) |
| [SecBench](notes/secbench.md) | C (knowledge) | 44,823 MCQ + 3,087 SAQ, multi-dimensional cyber QA | static dataset | model-selection screen only | [notes](notes/secbench.md) |
| [AgentBench](notes/agentbench.md) | A | 7 general agent envs (OS/DB/KG/games/web) | simulated envs | optional model-swap regression screen (OS/DB slices) | [notes](notes/agentbench.md) |
| [CAIBench](notes/caibench.md) | C+A | meta-benchmark: 5 categories, 10K+ instances, knowledge≠capability finding | per-module | **watch item** for new modules | [notes](notes/caibench.md) |

### Infra / governance / agent construction

| item | pillars | what it is (one line) | env / offline? | Shlepa fit | note |
| ---- | ------- | ---------------------- | -------------- | ---------- | ---- |
| [Agentic Security Harness](notes/agentic-security-harness.md) | S | local trace-first boundary-failure benchmark (vulnerable vs protected agent) | local, deterministic | run quickstart as self-security probe; study trace/scorecard format | [notes](notes/agentic-security-harness.md) |
| [EvalBench](notes/evalbench.md) | — | offline eval harness + **CI regression gates** | offline | optional tooling idea (baseline gate over our metrics) | [notes](notes/evalbench.md) |
| [NIST AI RMF GenAI Profile](notes/nist-genai-profile.md) | S (governance) | risk governance framework (GOVERN/MAP/MEASURE/MANAGE) | n/a | reading; vocabulary for the self-security eval design | [notes](notes/nist-genai-profile.md) |
| [PrivEsc-LLM](notes/privesc-llm.md) | A (local model) | 4B post-training (SFT+RL, verifiable rewards) → 93.3% on Linux privesc | n/a (paper) | **recipe for future local-model work** | [notes](notes/privesc-llm.md) |
| [Hackphyr](notes/hackphyr.md) | A (local model) | 7B local fine-tuned red-team agent ≈ GPT-4 on its envs | n/a (paper) | dataset-construction method; behavior analysis | [notes](notes/hackphyr.md) |
| [CTFJudge (alias)](notes/ctfjudge.md) | A | same paper as CTFTiny (2508.05674) — cross-reference | — | see CTFTiny | [notes](notes/ctfjudge.md) |

## Bottom line

- **Adapt into the dev loop now** (high value, low cost): SecCodeBench-V2
  scenarios, CrackMeBench tasks, a CTFTiny/NYU-CTF subset, 1–2 CVE-Bench
  web CVEs → `bench-<name>-*` Harbor tasks.
- **Steal the methods**: partial-credit checkpoints (DeepRed/CTFJudge),
  trajectory reward (CTI-REALM), utility×ASR + FRR reporting (AgentDojo /
  CyberSecEval 2), deterministic capability oracles (ExploitBench),
  injection-variant design (InjecAgent/AgentDojo).
- **Skip**: full CyberGym, ExploitBench, full SOCBench harness,
  SecBench/RedSage-Bench as agent evals, CAIBench as a dev tool.
- **Unverified in source list** (marked, not dropped): SecMind,
  VulnAgentBench.

See [`analysis/fit-matrix.md`](analysis/fit-matrix.md) for the full matrix
and concrete next steps.
