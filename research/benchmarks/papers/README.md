# Benchmark paper registry

Store each PDF as `<slug>.pdf` (slug = lowercase hyphenated, matching
`../notes/<slug>.md` where a note exists) and add one row per paper.
Download with `curl -L -o`; verify with `file`. If no paper exists for a
benchmark, record the primary source URL in the note and skip the registry.

| slug | title | link | why (one line) |
| ---- | ----- | ---- | -------------- |
| agentbench.pdf | AgentBench: Evaluating LLMs as Agents | https://arxiv.org/abs/2308.03688 | general agent-capability baseline (OS/DB slices) |
| agentdojo.pdf | AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents | https://arxiv.org/abs/2406.13352 | top agent-self-security reference (utility × ASR) |
| asb.pdf | Agent Security Bench (ASB): Formalizing and Benchmarking Attacks and Defenses in LLM-based Agents | https://arxiv.org/abs/2410.02644 | attack-stage taxonomy incl. memory poisoning / backdoors |
| caibench.pdf | Cybersecurity AI Benchmark (CAIBench): A Meta-Benchmark for Evaluating Cybersecurity AI Agents | https://arxiv.org/abs/2510.24317 | meta-benchmark watch item; knowledge≠capability finding |
| crackmebench.pdf | CrackMeBench: Binary Reverse Engineering for Agents | https://arxiv.org/abs/2605.10597 | no-network Docker RE tasks — first adaptation candidate |
| cti-realm.pdf | CTI-REALM: Benchmark to Evaluate Agent Performance on Security Detection Rule Generation Capabilities | https://arxiv.org/abs/2603.13517 | trajectory-based reward design to steal |
| ctftiny.pdf | Towards Effective Offensive Security LLM Agents (CTFTiny/CTFJudge/CCI) | https://arxiv.org/abs/2508.05674 | 50-challenge proving ground + partial-credit CCI |
| cve-bench.pdf | CVE-Bench: A Benchmark for AI Agents' Ability to Exploit Real-World Web Application Vulnerabilities | https://arxiv.org/abs/2503.17332 | 40 critical web-app CVEs (zero-day/one-day) |
| cybench.pdf | Cybench: A Benchmark for Evaluating Cybersecurity Capabilities and Risks of Language Models | https://arxiv.org/abs/2408.08926 | 40 professional CTF tasks, subtask gradation |
| cybergym.pdf | CyberGym: Evaluating AI Agents' Real-World Cybersecurity Capabilities at Scale | https://arxiv.org/abs/2506.02548 | 1,507 real vulns → PoC; subset-adaptation source |
| cyberseceval2.pdf | CyberSecEval 2: A Wide-Ranging Cybersecurity Evaluation Suite for LLMs | https://arxiv.org/abs/2404.13161 | injection + false-refusal-rate (FRR) tradeoff |
| cyberseceval3.pdf | CYBERSECEVAL 3: Advancing the Evaluation of Cybersecurity Risks and Capabilities in LLMs | https://arxiv.org/abs/2408.01605 | 8 risks incl. autonomous offensive ops |
| cybersoceval.pdf | CyberSOCEval: Benchmarking LLMs Capabilities for Malware Analysis and Threat Intelligence Reasoning | https://arxiv.org/abs/2509.20166 | SOC capability baseline (CyberSecEval 4) |
| deepred.pdf | Do Agents Dream of Root Shells? Partial-Credit Evaluation of LLM Agents in CTF | https://arxiv.org/abs/2604.19354 | partial-credit checkpoint method |
| exploitbench.pdf | ExploitBench: A Capability Ladder Benchmark for LLM Cybersecurity Agents | https://arxiv.org/abs/2605.14153 | 16-flag ladder + deterministic oracle design |
| hackphyr.pdf | Hackphyr: A Local Fine-Tuned LLM Agent for Network Security Environments | https://arxiv.org/abs/2409.11276 | local 7B red-team agent; dataset-construction method |
| injecagent.pdf | InjecAgent: Benchmarking Indirect Prompt Injections in Tool-Integrated LLM Agents | https://arxiv.org/abs/2403.02691 | 1,054 IPI cases; injection-variant recipe |
| nist-ai-600-1.pdf | NIST AI RMF: Generative AI Profile | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf | governance/risk vocabulary for self-security eval |
| nyu-ctf-bench.pdf | NYU CTF Bench: A Scalable Open-Source Benchmark Dataset for Evaluating LLMs in Offensive Security | https://arxiv.org/abs/2406.05590 | 200 prebuilt Docker CTF challenges — top adaptation candidate |
| privesc-llm.pdf | Towards Reliable Local Security Agents: Verifiable Post-Training for Linux Privilege Escalation | https://arxiv.org/abs/2603.17673 | 4B SFT+RL recipe (93.3% privesc) for local-model work |
| redsage.pdf | RedSage: A Cybersecurity Generalist LLM | https://arxiv.org/abs/2601.22159 | local cyber LLM + 30K-item RedSage-Bench |
| sec-bench.pdf | SEC-bench: Automated Benchmarking of LLM Agents on Real-World Software Security Tasks | https://arxiv.org/abs/2506.11791 | PoC + patching on auto-generated vuln repos ($0.87/instance) |
| sec-bench-pro.pdf | SEC-bench Pro: Can Language Models Solve Long-Horizon Software Security Tasks? | https://arxiv.org/abs/2605.26548 | 344 real V8/SpiderMonkey/kernel bugs; LLM judge for PoCs |
| secbench.pdf | SecBench: A Comprehensive Multi-Dimensional Benchmarking Dataset for LLMs in Cybersecurity | https://arxiv.org/abs/2412.20787 | 45K cyber QA — knowledge screen only |
| seccodebench-v2.pdf | SecCodeBench-V2 Technical Report | https://arxiv.org/abs/2602.15485 | 98 secure generation/fix scenarios, 22 CWEs — fix-family fit |
| swe-bench.pdf | SWE-bench: Can Language Models Resolve Real-World GitHub Issues? | https://arxiv.org/abs/2310.06770 | hidden-test verifier pattern reference |
| 3cb.pdf | Catastrophic Cyber Capabilities Benchmark (3CB) | https://arxiv.org/abs/2410.09114 | 15 MITRE-aligned offense challenges; robust elicitation |

Notes without a PDF (no paper exists — primary source is a repo/site):
`socbench`, `agentic-security-harness`, `evalbench`, `secmind-unverified`.
`ctfjudge` is an alias of `ctftiny.pdf`.
