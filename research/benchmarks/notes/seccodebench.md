# SecCodeBench (bonus find — secure code generation & repair)

- **Category:** vuln-fix (secure code generation/repair) — found during SOC
  batch research, not in the original source list
- **Source:** SecCodeBench-V2 Technical Report, arXiv 2602.15485, 2026
- **Paper:** https://arxiv.org/abs/2602.15485 (PDF: `papers/seccodebench-v2.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
LLM copilots' ability to **generate secure code** and **fix insecure code**:
98 generation + fix scenarios derived from **industrial production code
(Alibaba Group)**, spanning **22 CWE categories** across Java, C, Python,
Go, JavaScript. Function-level formulation: full project scaffold provided,
model implements or patches one designated target function under fixed
interfaces/dependencies.

## Environment
Static code scenarios (scaffold + function + tests); executable
**proof-of-concept test cases for both functional validation and security
verification**; all tests authored and double-reviewed by security experts.
Fully local/offline.

## Tasks
Generation (write a secure function from spec) and fix (repair an insecure
function) pairs per CWE.

## Scoring
Executable: functional tests must pass AND security PoC tests must confirm
the vulnerability is absent. No LLM judge.

## Fit for Shlepa
- **Overlap:** **directly overlaps `contest-fix-sqli-*`** — "fix the
  vulnerable function, keep functionality, prove the vuln is gone" is
  exactly our fix-task contract, with a cleaner two-sided test design
  (functional + security).
- **Offline feasibility:** excellent — plain code + tests.
- **Adaptation cost:** **low** — one scenario ≈ one Harbor task
  (`bench-seccodebench-*`); the CWE spread lets us cover SQLi, XSS,
  path traversal, injection variants matching our FastAPI app family.
- **Recommendation:** **first-priority adaptation candidate** alongside
  CrackMeBench: cheap, deterministic, and it tests the exact skill of the
  fix-sqli tasks (including the failure mode we most fear: fixing the vuln
  by breaking functionality).

## Adapted into Harbor tasks (2026-08-27, tag `v2.2.0`)

Three **fix-mode** Python scenarios vendored from
`alibaba/sec-code-bench` @ tag `v2.2.0` (commit `67126ef`, Apache-2.0)
into `tasks/bench-seccodebench-*`, per `docs/tasks.md`. Each task keeps a
byte-identical `upstream/` audit copy of the scenario plus the upstream
`LICENSE`, and a two-sided verifier (`tests/test.sh`): functional pytest
first, then security-PoC pytest; reward `1` only when **both** pass
(functionality-first protocol).

| Harbor task | Upstream scenario (`datasets/templates/python/2_1_0/…`) | CWE |
|---|---|---|
| `bench-seccodebench-cwe89` | `SQLInjectionPsycopg2` | CWE-89 (SQL injection) |
| `bench-seccodebench-cwe78` | `CommandInjectionSubprocessRun` | CWE-78 (OS command injection) |
| `bench-seccodebench-cwe1336` | `SSTIJinja2Template` | CWE-1336 (server-side template injection) |

All tests are fully mocked (no live services). The agent runs inside the
`secureintelligent/acp:latest` image against the scenario scaffold in
`/app`.

### First agent run (preset `seccodebench`, 2026-08-27)

| Task | Solved | Duration | Tokens (in/out/total) |
|---|---|---|---|
| bench-seccodebench-cwe89 | ✅ 1/1 | 179.7s | 45384 / 1652 / 47036 |
| bench-seccodebench-cwe78 | ✅ 1/1 | 211.2s | 73415 / 6626 / 80041 |
| bench-seccodebench-cwe1336 | ✅ 1/1 | 146.0s | 53324 / 2965 / 56289 |

Model: `Qwen3.8:27B-UD-IQ4_XS` (local llama.cpp, `LOCAL_AGENT_MODEL`), container mode, 3/3 solved on the first agent run. Verifier anomalies: none (all functional + security suites passed in-container).

## Sources
- Paper: https://arxiv.org/abs/2602.15485
- Index entry: https://benchmarklist.com/benchmarks/seccodebench/
- Upstream repo: https://github.com/alibaba/sec-code-bench (tag `v2.2.0`)
