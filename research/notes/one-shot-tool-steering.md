# One-shot Examples vs Steering for Custom Tool Usage

- **Category:** agent-architecture (prompting / tool selection)
- **Source:** local A/B on Qwen3.8:27B-UD-IQ4_XS (2026-09-06, 5 runs),
  vendor/community evidence on few-shot tool calling
- **Reviewed:** 2026-09-06
- **Related:** `v6-baseline-readonly-tools.md` (the tools being steered),
  `readonly-plan-phase.md` (the phase design)

## Question

The v6 baseline ships six orientation tools (plan) / nine (work). Steering
lives in `prompts/base.md` (ORIENTATION TOOLS) + `prompts/plan.md`
(orient-FIRST) + `prompts/work.md` (Exploration tools). Is steering
enough, or do the new tools need a **one-shot example** (call + result
shape) because the model's training prior is bash/grep/ls-first?

## Method

Task: `bench-soc-ntds-vss-b` (SOC incident analysis over a 512-record
Windows-event JSONL; known-solvable, ~4–7 min/run, `experiments/
ab-readonly.yaml`).
Arm A = steering only (HEAD `b69ff85`). Arm B = steering + one-shot: the
forensics example in plan.md shows abbreviated tool **outputs**, and
work.md gains a short `code_search → read` example (+~200 tokens/run).
Per-run measurement: trace spans
(`gen_ai.tool.name` / `gen_ai.tool.call.arguments` / `shlepa.phase_id`),
breakdown script `tmp/analyze_ab.py`.

## Results (5 runs)

| run | arm | agent s | tokens | work bash (exploratory/total) | plan tools | solved |
|---|---|---|---|---|---|---|
| A1 | steering | 253 | 112k | 3/5 | recon, triage, search×5, read×3 | ✓ |
| A2 | steering | 238 | 145k | 2/5 | recon, triage, read×4, search×1 | ✓ |
| A3 | steering | 328 | 131k | 1/3 | triage, read×4, search×5 | ✗ (indicator not verbatim in evidence) |
| B1 | +one-shot | 235 | 133k | 5/8 | triage, search×2, read×2 | ✓ |
| B2 | +one-shot | 166 | 109k | 0/2 | recon, triage, read×4 | ✓ |

(triage = log_triage; "exploratory" = bash used for what a custom tool
covers: raw `cat` of evidence, `wc -l`/`jq` counts, exact-text `grep`;
mechanical deliverable validation is sanctioned by work.md and excluded.)

### Findings

1. **Steering reliably drives the PLAN phase in every run, both arms**
   (log_triage ×1 always; recon most runs; the prompt's
   recon→log_triage→search→read script is followed). Caveat: plan has no
   bash, so part of this is enforced by tool absence, not preference.
2. **The WORK phase bash prior persists in BOTH arms**: the model
   re-explores with bash (`cat` of the raw evidence files, `wc -l`/`jq`
   counts, exact-text `grep` for pentest markers) 1–3 calls/run in A and
   0–5 in B. Averages: A 2.0/run, B 2.5/run — **no consistent effect of
   the one-shot** at n=5 (B's range 0–5 is wider than A's 1–3).
3. B2 is the ideal run (zero exploratory bash; plan findings reused),
   B1 the worst (8 bash calls) — the example neither guaranteed the good
   run nor prevented the bad one.
4. A3's failure is a content-accuracy issue (key indicator
   `DC01.corp.local` not present verbatim in the evidence), orthogonal to
   tool selection; noted for the accuracy backlog.
5. Descriptions alone were already near-dead in the v3 corpus
   (code_search 2/98 runs, log_triage 1/49, file_outline 1/49);
   steering lifts plan-phase usage; neither lifting work-phase selection
   has been demonstrated at this model scale.

## External evidence (supports examples in general, not decisive here)

- **LangChain (2024-07), multi-model experiments**: few-shot tool-call
  examples lift tool-selection recall substantially — Claude 3 Sonnet
  16% (zero-shot) → 52% (3 examples as chat messages); messages beat
  system-string concatenation; 3 examples ≈ 13.
- **Anthropic (2025-11), "advanced tool use"**: "wrong tool selection and
  incorrect parameters" named as the most common tool-use failures; ships
  Tool Use Examples (sample calls in tool definitions) after internal
  testing showed 72% → 90% on complex parameter handling; guidance:
  realistic data, 1–5 examples per tool, only where non-obvious.
- **Comet (2026-03)**: tool-calling is the agentic category that benefits
  most from few-shot; turn repeated trace failures into examples; 3–5
  strong, varied, realistic examples; sparing negative examples clarify
  boundaries.

Caveats: all frontier-model evidence; our agent runs a local 27B
quantized model with stronger bash/grep/ls priors. llama.cpp's
OpenAI-compatible API has no `input_examples` mechanism, so prompt-
embedded examples are the only lever here.

## Decision

**Keep the steering-only prompts (HEAD). Do not adopt the one-shot** —
no measurable benefit at n=5, +~200 tokens/run, and the plan-phase
example's marginal value is unclear (plan followed the script in arm A
too). The one-shot text is preserved in the git history of this
experiment (draft: `tmp/ab-armB-draft.txt`).

## Next levers (untested, for a follow-up A/B)

1. **Relay fidelity** (structural, cheapest): the work phase re-explores
   because the plan's triage output (IOC candidates + exact line refs)
   arrives distilled; carry it verbatim into the work prompt's RESULTS
   block so there is no *need* to re-`cat` the raw evidence.
2. **Negative example in work.md** targeting the observed anti-pattern:
   "do not `cat` raw evidence files — `log_triage(path=...)` then
   `read(path=..., offset=...)`" (Comet: sparing negative examples for
   boundary-setting).
3. **Model scale**: on a stronger model the steering may suffice; the
   bash prior is a 27B-IQ4 artifact, not necessarily a prompt defect.

## Sources

- Local: `tmp/trace-export/{20260906-064808-bc8fb7, 20260906-071939-
  7b4d23, 20260906-073624-d59c59, 20260906-065905-ec2cfd,
  20260906-070937-09bcf1}/` (per-run span dumps + digests),
  `tmp/analyze_ab.py` (per-phase/per-tool breakdown),
  `tmp/ab-arm{A,A2,A3,B,B2}.log` (run logs), `experiments/
  ab-readonly.yaml` (A/B preset, untracked).
- External: langchain.com/blog/few-shot-prompting-to-improve-tool-calling-
  performance; anthropic.com/engineering/advanced-tool-use;
  comet.com/site/blog/few-shot-prompting/.
