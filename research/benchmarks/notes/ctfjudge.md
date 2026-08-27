# CTFJudge / CTF Competency Index (alias note)

- **Category:** ctf evaluation methodology
- **Source:** same paper as CTFTiny — arXiv 2508.05674
- **Paper:** https://arxiv.org/abs/2508.05674 (PDF: `papers/ctftiny.pdf`)
- **Code:** https://github.com/NYU-LLM-CTF/CTFJudge
- **Reviewed:** 2026-08-27

The source list tracks "Towards Effective Offensive Security LLM Agents"
(CTFJudge/CCI) as a separate paper from CTFTiny. It is **the same
paper**: CTFTiny is the 50-challenge benchmark introduced in it, and
CTFJudge/CCI are its evaluation contributions.

Full digest: see [`ctftiny.md`](ctftiny.md).

Key takeaways repeated here for the agent-construction pillar:
- **CTFJudge**: LLM-as-judge over agent *trajectories* (not just final
  answers) — granular per-step evaluation of CTF solving.
- **CCI (CTF Competency Index)**: partial-correctness metric vs
  human-crafted gold standards.
- Hyperparameter findings (temperature/top-p/max-length effects on
  offensive agent success) — directly applicable to Shlepa's sampling
  configuration.

## Sources
- Paper: https://arxiv.org/abs/2508.05674
- See also: `ctftiny.md`
