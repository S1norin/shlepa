# Cybench (NVIDIA)

- **Category:** ctf (professional-level, capability + risk)
- **Source:** NVIDIA Research (ai-ix), arXiv 2408.08926, 2024
- **Paper:** https://arxiv.org/abs/2408.08926
- **Site:** https://cybench.github.io/ (leaderboard, task specs)
- **Reviewed:** 2026-08-27

## What it tests
Offensive cybersecurity **capabilities and risks** of LM agents on **40
professional-level CTF tasks from 4 distinct CTF competitions**, chosen to be
recent, meaningful, and spanning a wide difficulty range. Tasks are broken
into **subtasks** (intermediary steps with own questions/answers) for
graduated evaluation.

## Environment
Each task: description + starter files + evaluator. Environment =
**Kali Linux container** with task-specific local files and any task
server(s); the agent interacts via **bash commands** locally and network
calls to remote files. Very close to our container+bash agent model.

## Tasks
6 standard CTF categories: crypto, forensics, reverse engineering, pwn, web,
misc (professional difficulty — above picoCTF level).

## Scoring
- Unguided % solved (no subtask guidance)
- Subtask-guided % solved
- Subtasks % solved per task (macro-averaged)
- Hardest task solved, by human first-solve-time (FST)
Public leaderboard; model system cards report on subsets.

## Fit for Shlepa
- **Overlap:** CTF-style; web/pwn tasks overlap with vuln finding/fixing
  skills, forensics tasks with incident response.
- **Offline feasibility:** high per task — container + local files; server
  tasks need their server container (fine in our env builder).
- **Adaptation cost:** low — one CTF task ≈ one Harbor task
  (`bench-cybench-<slug>`): env image + instruction + evaluator as test.sh.
- **Recommendation:** good source for 1–2 individual dev tasks. Watch
  **BountyBench** (linked from cybench.github.io): real-world vulnerability
  detection/exploitation/**patching** with dollar impact — directly
  overlaps the `contest-fix-sqli-*` family; worth a dedicated note later.

## Sources
- Paper: https://arxiv.org/abs/2408.08926
- Site/leaderboard: https://cybench.github.io/
