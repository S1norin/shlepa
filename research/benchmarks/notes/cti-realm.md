# CTI-REALM

- **Category:** soc (detection engineering: CTI → detection rules)
- **Source:** Microsoft Research, arXiv 2603.13517, 2026
- **Paper:** https://arxiv.org/abs/2603.13517 (PDF: `papers/cti-realm.pdf`)
- **Reviewed:** 2026-08-27

## What it tests
Agents' ability to **interpret cyber threat intelligence (CTI) and develop
detection rules** — a realistic security-analyst workflow: examine CTI
reports, execute queries, understand data schemas, construct detection
rules. Emulated attacks of varying complexity on **Linux, cloud platforms,
and Azure Kubernetes Service (AKS)**, with ground truth.

## Environment
Replicated detection-engineering environment (analyst workspace +
emulated attack traffic across Linux/cloud/AKS); CTI-specific tools
provided to the agent (ablation: they significantly improve performance).

## Tasks
CTI → detection-rule construction per scenario, with emulated attacks as
ground truth; 16 frontier models evaluated. Best: Claude Opus 4.6 (High)
overall reward **0.637**; Opus 4.5 0.624; GPT-5 family follows.

## Scoring
**Two-part reward: final detection result + trajectory-based reward**
capturing decision-making effectiveness (not just the answer). Variance
analysis across repeated runs shows stability; memory augmentation
(seeded context) closes ~33% of the small-model vs large-model gap.

## Fit for Shlepa
- **Overlap:** defensive detection engineering — adjacent to our forensics
  family; rule generation itself is new territory for us.
- **Offline feasibility:** medium — needs emulated attack environments
  (Linux/cloud/AKS); the AKS part is heavy for our 2 GB dev containers.
- **Adaptation cost:** high for the full benchmark; **low for the idea**.
- **Recommendation:** do not port the benchmark now. **Steal the scoring
  design**: trajectory-based reward on top of the final answer (tool
  selection, evidence quality, policy compliance, cost) — exactly what our
  binary `reward.txt` lacks, and it matches the "score the investigation,
  not just the flag" principle from the source list. Also relevant to
  agent-security work: trajectory scoring exposes when an agent "gets the
  right answer the wrong way".

## Sources
- Paper: https://arxiv.org/abs/2603.13517
- MSR page: https://www.microsoft.com/en-us/research/publication/cti-realm-benchmark-to-evaluate-agent-performance-on-security-detection-rule-generation-capabilities/
