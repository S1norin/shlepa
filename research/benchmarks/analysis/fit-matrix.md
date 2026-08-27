# Fit matrix & recommendations

Cross-cutting analysis of the benchmarks in this directory against Shlepa's
actual situation. Sources: the per-benchmark notes in `../notes/`.

## Context: what the competition tasks actually are

From the vendored contest tasks (`tasks/README.md`), the Shlepa agent faces
four task families, all run as **one agent in one Docker container**
(`secureintelligent/acp:latest`), scored by an **executable verifier**
(`tests/test.sh` → binary `reward.txt`):

| family | example task | core skill |
| ------ | ------------ | ---------- |
| **vuln-find** | `contest-find-sqli-login` | read code, identify vulnerabilities, emit machine-readable JSON |
| **vuln-fix** | `contest-fix-sqli-login`, `contest-fix-sqli-search` | find a bug, patch it, keep functionality |
| **forensics** | `contest-incident-log-forensics` | correlate multiple logs, attribute an incident |
| **basic-ops** | `contest-hello-file` | trivial file operations (calibration only) |

Hard constraints: per-task time budget, token budget, container resource
limits (≈2 GB RAM, no GPU), offline/sandboxed submission runs.

## Matrix

C = competition family overlap (F=find, X=fix, I=forensics, –=none) ·
OFF = offline feasibility · COST = cost to adapt into a Harbor task ·
P = pillar (C=cyber, A=agent, S=self-security).

| benchmark | C | OFF | COST | P | verdict |
| --------- | -- | --- | ----- | -- | ------- |
| SecCodeBench-V2 | F,X | excellent | low | C | **adapt now** |
| CrackMeBench | – (agent probe) | excellent | low | A | **adapt now** |
| CTFTiny | F,X,I (subset) | high | low | C+A | **adapt now** (proving ground) |
| NYU CTF Bench | F,X,I (subset) | high | low | C+A | **adapt now** |
| CVE-Bench | F (demonstrate) | high | medium | C | adapt 1–2 |
| SEC-bench | F,X | high | medium | C | **task factory** for F/X |
| CyberGym | F | high (storage!) | medium | C | adapt small subset |
| SOCBench | I | high | medium | C+A | mine 2–3 scenarios |
| Cybench | F,X,I (subset) | high | low | C | single-task source; watch BountyBench |
| DeepRed | I (subset) | medium | medium | C+A | **steal partial-credit method** |
| AgentRE-Bench | – (agent probe) | excellent | low | A | adapt a few levels |
| AgentDojo | I (variants) | excellent | low | S | **top self-security ref** |
| InjecAgent | – (variants) | excellent | low | S | injection-variant recipe |
| ASB | – | high | medium | S | threat-model catalog |
| Agentic Security Harness | – | excellent | low | S | run as ad-hoc probe |
| CyberSecEval 2/3 | – | excellent | low | S | model-swap screen; steal FRR |
| CyberSOCEval | I (knowledge) | high | low | C | knowledge baseline |
| CTI-REALM | I (adjacent) | medium | high | C+A | **steal trajectory scoring** |
| 3CB | F (offense) | high | medium | C | threat-model reference |
| ExploitBench | – | high | high | C | skip; steal ladder/oracle design |
| SWE-bench | X (pattern) | excellent | low | A | keep verifier pattern; optional probes |
| AgentBench | – | excellent | low | A | optional model-swap screen |
| SecBench | – | excellent | low | C | model screen only |
| RedSage-Bench | – | excellent | low | C | model screen; local-model recipe |
| CAIBench | – | varies | n/a | C+A | watch item |
| EvalBench | – | excellent | low | – | optional CI-gate idea |
| NIST AI 600-1 | – | n/a | n/a | S | reading; risk vocabulary |
| PrivEsc-LLM / Hackphyr | – | n/a | n/a | A (model) | recipes for local-model work |
| SecMind, VulnAgentBench | — | — | — | — | **unverified — ignore** |

## Recommendations

### 1. Dev-eval adaptation (highest ROI, do first)

Adapt, in order, as Harbor tasks with the `<bench>-` prefix per
`docs/tasks.md` (provenance keys + registry row each):

1. **`bench-crackme-<n>`** (3–4 tasks from CrackMeBench's generated split):
   no-network Docker + standard RE tools + 5-min budget + oracle scoring —
   this is literally our submission environment. Fast, deterministic
   agent-capability signal.
2. **`bench-seccodebench-<cwe>`** (2–3 scenarios, incl. one SQLi and one
   injection CWE): tests the exact fix-sqli contract with a two-sided
   verifier (functional + security PoC) — upgrades how we can verify our
   own fix tasks too.
3. **CTFTiny/NYU-CTF subset** (2–3 challenges: 1 web, 1 forensics, 1 pwn,
   no-internet): recurring "proving ground" set for agent regressions.
4. **`bench-cve-bench-<cve>`** (1–2 web CVEs, e.g. SQLi→RCE): measures
   whether the agent can *demonstrate* a vulnerability, not just report it.

Target: ≈8–10 bench tasks in the dev preset, all offline, all
deterministically scored.

### 2. Methods to steal (no benchmark running required)

- **Partial credit**: binary `reward.txt` is our biggest dev-loop
  weakness. DeepRed (checkpoints from writeups + trace-grounded judge) and
  CTFTiny (CCI vs gold standard) both solve this; CTI-REALM's
  final+trajectory two-part reward adds the "right answer, wrong way"
  dimension. → Backlog: add an optional partial-reward channel to the
  dev engine.
- **Adversarial variants (agent self-security)**: for every task T create
  T+poison (hostile instructions inside a fixture: log line, file content,
  code comment, tool output). Score the pair as **(utility, ASR)**, with
  FRR (CyberSecEval 2) for the over-refusal failure mode. AgentDojo is
  the reference implementation; InjecAgent supplies the tool-poisoning
  vector; ASB's attack-stage taxonomy (system prompt / user prompt / tool
  / memory) is the checklist.
- **Deterministic oracles over LLM judges**: ExploitBench and AgentRE-Bench
  both grade with executable oracles + hallucination penalties. Keep
  verifiers executable; use LLM judges only where the artifact is
  unstructured (and then, trace-grounded, per DeepRed).
- **Cost-aware evaluation**: ExploitBench's 300-turn budget and
  CrackMeBench's 5-min/3-submission budget are templates for budget
  reporting in our MLflow runs (we already log `duration_sec`, tokens).

### 3. Model-side (only if a local/fine-tuned model gets prioritized)

PrivEsc-LLM (SFT on agent traces → RL with verifiable rewards, 4B at
93.3% on a verifiable security task), Hackphyr (task-specific dataset
construction), and RedSage (data curation + agentic SFT) form a coherent,
recent recipe. Our Harbor tasks + verifiers are exactly the "procedural
environment with verifiable reward" substrate such post-training needs.
CyberSOCEval's negative result (test-time scaling doesn't transfer to SOC
domains) matters for choosing reasoning settings.

### 4. Explicitly skipped

- **ExploitBench** — frontier binary exploitation; far beyond our task
  set and budget. Design ideas only.
- **CyberGym (full)** — 240 GB+ / 1,507 instances; subset only.
- **SOCBench (full harness)** — SIEM stack is heavy; mine scenarios.
- **SecBench / RedSage-Bench as agent evals** — QA knowledge, not agent
  behavior; model screens only.
- **CAIBench / EvalBench / NIST** — watchlist / tooling / reading.
- **SecMind, VulnAgentBench** — could not be verified; treat as
  hallucinated source entries.

## Open threads

- [ ] Port the first batch (CrackMeBench + SecCodeBench) via
  `shlepa task new bench-...` — separate work item, not research.
- [ ] BountyBench (NVIDIA, real-world vuln detection/exploitation/patching
  with dollar impact) — linked from cybench.github.io; deserves its own
  note when the task-selection follow-up starts.
- [ ] Partial-credit dev-engine channel (see Methods).
- [ ] Adversarial-variant design doc using the utility×ASR+FRR model.
