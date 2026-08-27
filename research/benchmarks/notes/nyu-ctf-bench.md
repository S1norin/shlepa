# NYU CTF Bench

- **Category:** ctf (scalable open challenge database)
- **Source:** NYU (LLM-CTF group), arXiv 2406.05590, 2024
- **Paper:** https://arxiv.org/abs/2406.05590 (PDF: `papers/nyu-ctf-bench.pdf`)
- **Code/Data:** github.com/NYU-LLM-CTF (dataset + automated framework)
- **Reviewed:** 2026-08-27

## What it tests
LLMs solving **CTF challenges from popular competitions**: a scalable,
open-source benchmark database of **200 manually validated challenges** from
CSAW CTF (2011–2023), with an automated evaluation framework using LLM
function calling + external tool support.

## Environment
Per challenge: a **JSON metadata file** (name, description, visible files,
server host + ports, hidden flag) and, for server challenges, a
**docker-compose.yml** pulling pre-built Docker Hub images. Server challenges
run on a Docker network; only files listed in the JSON are visible to the
model (mimics real CTF conditions). All source/config files included for
benchmark maintainers.

## Tasks
Categories include crypto, pwn (buffer overflow/UAF, checksec-gated), web,
forensics, misc — mixed local-file and server-based challenges across a
wide difficulty range.

## Scoring
Binary flag match per challenge (ground-truth flag hidden from model).

## Fit for Shlepa
- **Overlap:** CTF; web/pwn/forensics items map to our vuln finding/fixing
  and incident families.
- **Offline feasibility:** high — pre-built images, no external services;
  validate chosen challenges work with `--network host` or no network.
- **Adaptation cost:** **low — the closest structural match to Harbor
  format of anything researched**: JSON metadata → `task.toml` +
  `instruction.md`; Docker image → `environment/`; flag check →
  `tests/test.sh`. Individual challenges are self-contained.
- **Recommendation:** **top candidate for vendor adaptation.** Pick a few
  challenges (1 web, 1 forensics, 1 pwn) solvable without internet, port as
  `bench-nyuctf-*`, use as a recurring dev-eval set.

## Sources
- Paper: https://arxiv.org/abs/2406.05590
- Code: https://github.com/NYU-LLM-CTF
