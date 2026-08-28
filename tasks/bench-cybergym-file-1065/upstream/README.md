# Upstream provenance

- Task: CyberGym `arvo:1065` (project `file`/libmagic, OSS-Fuzz bug 1065)
- Vulnerability description: `description.txt` — verbatim from the
  CyberGym dataset (`data/arvo/1065/description.txt`,
  https://huggingface.co/datasets/sunblaze-ucb/cybergym)
- Expected crash report: `error.txt` — verbatim from the CyberGym dataset
  (`data/arvo/1065/error.txt`); this is the reference run of the
  vulnerable MSAN build on the original crash input.
- License: CyberGym is Apache-2.0 (see `LICENSE`, from
  https://github.com/sunblaze-ucb/cybergym).
- Environment: the task environment is NOT vendored here; it is built from
  the ARVO Docker images `n132/arvo:1065-vul` / `n132/arvo:1065-fix`
  (https://hub.docker.com/r/n132/arvo, https://github.com/n132/ARVO).
  Those images contain the `file` project source at its vulnerable and
  patched versions under their own upstream license (BSD-style), plus the
  OSS-Fuzz fuzzer harness.
- Reference PoC: `../solution/poc.bin` — the original OSS-Fuzz crash
  input, extracted from the ARVO `1065-vul` image (`/tmp/poc`), where it
  is removed from the agent environment.
