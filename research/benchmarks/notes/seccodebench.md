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

## Sources
- Paper: https://arxiv.org/abs/2602.15485
- Index entry: https://benchmarklist.com/benchmarks/seccodebench/
