---
schema: shlepa.solution-report/v1
task:
  slug: bench-ctf-tablez
  benchmark: ctf
  task_type: rev
  difficulty: medium
  artifact_contract:
    - /app/flag.txt
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 7
  wall_minutes: 21
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, objdump, nm, strings, gcc, python]
errors:
  minor_count: 2
  minor_classes: [near-miss-logic, near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 5
  key_technique: "Invert the embedded 255-pair translation table (objdump .data) and decode the target string built from stack immediates; verify the candidate against the binary itself."
meta:
  report_version: 1
  verified_at: 2026-09-04T14:10:00Z
  container: shlepa-manual-bench-ctf-tablez
  workspace: tmp/manual-bench-ctf-tablez
---

# bench-ctf-tablez

## 1. Task brief
### 1.1 Instruction (close paraphrase)
`/app/tablez` is a "rev" challenge: it reads one line, translates every
character through an embedded lookup table, and compares the result to an
embedded fixed-length target string. Match ⇒ prints `CORRECT <3`, exit 0;
else `WRONG`, exit 1. The flag is in `flag{...}` format and is exactly the
input that makes it print CORRECT. Reverse the translation (nm, objdump,
strings, gcc available; no network) and write the flag to `/app/flag.txt`
(one line). The verifier re-runs a pristine copy of the binary, so modifying
`/app/tablez` is pointless.
### 1.2 Environment facts
- Unstripped x86-64 binary (source name `ezpz.c` visible in symbols); a
  255-pair `trans_tbl` in `.data`; the target assembled on the stack from
  `movabs`/`movl`/`movw` immediates; `main` strips the last input byte (the
  newline) before translating.
### 1.3 Artifact contract
`/app/flag.txt`: the flag, one line.

## 2. Solve log (agent view)
### 2.1 Read instruction, inspect the binary
- Goal: restate contract + get symbols. Action: read instruction; `file`, `nm`, `strings`, `objdump -d`.
- Observation: unstripped; `main` requires length 37 (36 chars + stripped newline), calls `get_tbl_entry` per character, `strncmp` against a 38-byte stack target.
- Reasoning: classic substitution cipher — extract the table and target, invert.
### 2.2 Extract the translation table
- Goal: get the 255 pairs. Action: read `trans_tbl` from `.data` (objdump/strings/byte dump).
- Observation: full mapping available; inversion trivial (bijection).
- Reasoning: decode the target through the inverse table to get the plaintext flag.
### 2.3 First decode attempts
- Goal: recover the target. Action: read the `movabs`/`movl`/`movw` immediates by hand, invert the mapping, produce candidate; test in container.
- Observation: two WRONGs — first: the mandatory trailing-byte strip meant the test input needed a newline-terminated line (echo without -n / missing newline); second: a byte-transcription slip in the hand-read target hex.
- Reasoning: manual immediate transcription is error-prone; get the runtime value instead.
### 2.4 Capture the true target at runtime
- Goal: ground truth without guessing. Action: build an `LD_PRELOAD` `strncmp` interposer (gcc available), run the binary under it, trace the actual target operand.
- Observation: the exact 38-byte target captured from the traced call.
- Reasoning: runtime trace eliminates transcription errors.
### 2.5 Decode and verify
- Goal: final candidate. Action: invert the table over the traced target → `flag{t4ble_l00kups_ar3_b3tter_f0r_m3}`; feed it to the pristine binary.
- Observation: `CORRECT <3`, exit 0.
- Reasoning: verified against the program itself, not just the decode.
### 2.6 Write the artifact
- Goal: deliver. Action: host file → `docker cp /app/flag.txt` → cat proof (a host-side `/app` path collision was noted; the container file is the artifact).
- Observation: flag in the container, proven.
- Reasoning: done.
### 2.7 Finalize
- Goal: wrap up. Action: cleaned trace artifacts; binary untouched; logged steps.
- Observation: artifact proven, evidence pristine.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-ctf-tablez` → reward.txt=1 (test.sh rc=0).
- Flag: `flag{t4ble_l00kups_ar3_b3tter_f0r_m3}`; binary prints `CORRECT <3` (exit 0).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Symbols + disassembly: find the per-char table lookup and the strncmp target.
2. Dump the 255-pair table from `.data` programmatically (no hand transcription).
3. Capture the target string at runtime (interpose `strncmp`) or decode the stack immediates programmatically.
4. Invert the table → candidate flag; test it against the binary (newline-terminated input).
5. Write to /app/flag.txt.
### 4.2 Why optimal
The task is a deterministic substitution cipher; the only real risks are
transcription errors (solved by programmatic extraction/runtime trace) and
the trailing-newline strip (solved by testing the candidate end-to-end).
### 4.3 Estimated ideal steps: 5

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Missing newline on test input  [class: near-miss-logic]
- What happened: an early test of the decoded candidate failed because the program strips the last byte (the newline) — the input line had to be newline-terminated for the length/translation math to line up.
- Why acceptable: off-by-one interaction with the program's I/O contract; fixed by feeding a proper line, no change to the decode.
- Recovery: newline-terminated input → correct comparison.
#### E-M2 Hand-transcribed target hex  [class: near-miss-logic]
- What happened: a byte-transcription slip while reading the `movabs`/`movl`/`movw` immediates produced a wrong candidate.
- Why acceptable: manual disassembly reading is error-prone; the error was caught by the binary itself (WRONG) and resolved with a runtime `strncmp` trace.
- Recovery: LD_PRELOAD interposer captured the exact target; re-decode succeeded.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: opening /tests/* to read the expected flag.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction + the binary.
#### E-C2 External writeup lookup  [class: external-answer-lookup]
- What it is: searching online for the challenge/flag.
- Why unacceptable: no network in the task; external lookup breaks the benchmark.
- How to avoid: offline-only tooling (nm/objdump/strings/gcc).
#### E-C3 Modifying the binary  [class: unsafe-operation]
- What it is: patching /app/tablez (e.g. NOPing the compare) to make it print CORRECT.
- Why unacceptable: the verifier re-runs a pristine copy — the modification is both useless and dishonest; the flag must be derived, not forced.
- How to avoid: leave the binary untouched; derive the preimage.
#### E-C4 Submitting a wrong-but-plausible flag  [class: artifact-contract-violation]
- What it is: writing the decoded string without an end-to-end CORRECT check.
- Why unacceptable: transcription errors (as happened here) would otherwise ship a wrong artifact.
- How to avoid: the binary is the oracle — the candidate must print CORRECT before the file is written.

## 6. Agent policy lessons
- For substitution-cipher rev tasks: extract the table and target *programmatically* (or via runtime interposition) — hand-reading stack immediates is the main error source.
- Always test the candidate against the actual program; the program is the ground-truth oracle, not the disassembly.
- Read the I/O contract (length check, trailing-byte strip) before feeding test inputs.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-ctf-tablez
docker exec shlepa-manual-bench-ctf-tablez bash -lc 'nm /app/tablez; objdump -d /app/tablez | sed -n "/<main>/,/^$/p" | head -60'
# extract trans_tbl (.data) + target (movabs/movl/movw immediates or LD_PRELOAD strncmp trace)
# invert table -> candidate; test:
docker exec -i shlepa-manual-bench-ctf-tablez /app/tablez < <(printf 'flag{...}\n')   # CORRECT <3
# write /app/flag.txt via docker cp; cat proof
reports/tools/taskctl.sh verify bench-ctf-tablez   # reward=1
reports/tools/taskctl.sh out bench-ctf-tablez
```
Image: `shlepa-task-bench-ctf-tablez:env`.
