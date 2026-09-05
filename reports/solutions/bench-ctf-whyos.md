---
schema: shlepa.solution-report/v1
task:
  slug: bench-ctf-whyos
  benchmark: ctf
  task_type: forensics
  difficulty: hard
  artifact_contract:
    - /app/flag.txt
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 8
  wall_minutes: 24
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, grep, file-extract, python-parse]
errors:
  minor_count: 1
  minor_classes: [over-exploration]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 5
  key_technique: "Timeline forensics: the flag is the 32-hex token the user typed into the tweak's 'flag content' field, logged verbatim by the Preferences process at the moment the keyboard session ended."
meta:
  report_version: 1
  verified_at: 2026-09-04T14:10:00Z
  container: shlepa-manual-bench-ctf-whyos
  workspace: tmp/manual-bench-ctf-whyos
---

# bench-ctf-whyos

## 1. Task brief
### 1.1 Instruction (close paraphrase)
`/app/whyos/` holds evidence from a jailbroken iOS device: `console.log`
(~23 MB system console log) and a `.deb` app package. Somewhere in these files
an attacker left a CTF flag — a 32-character lowercase hex string, no braces,
no prefix. Recover it and write it exactly as found (single line) to
`/app/flag.txt`.
### 1.2 Environment facts
- `console.log`: ~156k lines of iOS syslog format (severity, timestamp,
  process, message); a .deb whose dylib turned out to be a hand-crafted hollow
  Mach-O (zero `__text` size, no code, no strings) — a decoy.
### 1.3 Artifact contract
`/app/flag.txt`: the flag on a single line, exactly as found.

## 2. Solve log (agent view)
### 2.1 Read instruction, inventory evidence
- Goal: restate contract + see the evidence. Action: read instruction; ls; sizes.
- Observation: 23 MB log, one .deb; flag = 32 lowercase hex, exact copy.
- Reasoning: exactness means the flag appears verbatim somewhere — find the line that carries it.
### 2.2 Brute 32-hex scan of the log
- Goal: cheap first pass. Action: grep 32-hex candidates.
- Observation: 13 candidates, all false positives (Apple asset URLs, UUID fragments, BLE data).
- Reasoning: the flag is not a raw hex blob anywhere obvious; it must be identified by context.
### 2.3 Deep-dive the .deb
- Goal: check the app package for the flag or a hint. Action: extract (dpkg-deb), inspect the dylib.
- Observation: the tweak "whyOS" is a settings UI with a "flag content" text field and a "Set flag" button; the dylib is a hollow Mach-O (no code) — a deliberate decoy.
- Reasoning: the app is a red herring; the field UI hints the user *typed* a value, which the OS may have logged.
### 2.4 Reconstruct the user timeline
- Goal: find when the user interacted with the tweak. Action: parse the log around 19:10–19:12.
- Observation: 19:10:39 Preferences opens → 19:10:53 `amfid` loads `whyOSsettings.bundle` (the tweak UI) → 19:10:45–19:12:18 keyboard-assertion bursts (typing) → 19:12:18.81 keyboard session ends.
- Reasoning: a typed 32-hex value will surface in the logs around the moment typing stops.
### 2.5 Pin the exact line
- Goal: find the token at the typing end. Action: scan the lines at/after 19:12:18.81.
- Observation: line 97189 — `default 19:12:18.884704 -0400   Preferences ca3412b55940568c5b10a616fa7b855e`: the Preferences process logs the entered value verbatim, the only line where a process's entire message is a bare 32-hex token.
- Reasoning: context (process, timing, shape) identifies it uniquely.
### 2.6 Validate uniqueness and format
- Goal: rule out alternatives. Action: full-line shape scan over all 156k lines; check `[0-9a-f]{32}` exactly.
- Observation: exactly one match; format check passes.
- Reasoning: no ambiguity.
### 2.7 Write the artifact
- Goal: deliver. Action: host file → `docker cp /app/flag.txt` → cat proof.
- Observation: `ca3412b55940568c5b10a616fa7b855e` in the container.
- Reasoning: exact copy, single line.
### 2.8 Finalize
- Goal: wrap up. Action: log steps; clean host copies of the big log.
- Observation: artifact proven in container.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-ctf-whyos` → reward.txt=1 (test.sh rc=0).
- Flag: `ca3412b55940568c5b10a616fa7b855e` (console.log line 97189).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read the log's format + the .deb's role (tweak UI with a text field → user typed something).
2. Reconstruct the interaction timeline (UI load, keyboard bursts, session end).
3. Look for the typed value in the log lines bracketing the typing end.
4. Validate uniqueness (only line whose entire message is a bare 32-hex token) and format.
5. Write the exact token to /app/flag.txt.
### 4.2 Why optimal
The hollow dylib is a decoy designed to waste time in the binary; the real
signal is temporal (typing → log). Timeline-first beats pattern-first here.
### 4.3 Estimated ideal steps: 5

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Decoy deep-dive  [class: over-exploration]
- What happened: substantial time was spent byte-level analysis of the .deb's hollow Mach-O before pivoting to the timeline.
- Why acceptable: the .deb was explicitly in the evidence and the hollow result (no code, no strings) is itself a finding that rules it out; the cost was time, not correctness.
- Recovery: pivot to the log timeline, which identified the flag uniquely.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 External flag lookup  [class: external-answer-lookup]
- What it is: searching the internet for the flag or the challenge writeup.
- Why unacceptable: the flag is device-specific evidence; online lookup breaks the simulation and the benchmark's integrity.
- How to avoid: no network, ever, for CTF evidence tasks.
#### E-C2 Reporting a false-positive hex token  [class: artifact-contract-violation]
- What it is: submitting any of the 13 raw 32-hex candidates (URLs, UUIDs, BLE) without contextual validation.
- Why unacceptable: "exactly as found" plus the unique-context requirement makes non-unique matches wrong.
- How to avoid: require the candidate to be uniquely identified (context/shape), not just format-matching.
#### E-C3 Reading the verifier  [class: verifier-leak]
- What it is: opening /tests/* to learn the flag.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: only the instruction + /app evidence.
#### E-C4 Modifying evidence  [class: unsafe-operation]
- What it is: writing into /app/whyos/ (the evidence dir) while "cleaning up".
- Why unacceptable: evidence must stay pristine for re-verification.
- How to avoid: work on host copies; only create the flag.txt artifact.

## 6. Agent policy lessons
- "Exact as found" + a large log ⇒ the flag is a *line*, not a pattern: find the line whose context proves it (process, timing, shape), then validate uniqueness.
- Decoys (hollow Mach-O) are a time-sink by design; a 5-minute budget on the binary, then pivot to temporal analysis.
- Keyboard/session timestamps are the forensic anchor for "what did the user type": type-burst start/end bracket the token's appearance.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-ctf-whyos
docker cp shlepa-manual-bench-ctf-whyos:/app/whyos/console.log tmp/manual-bench-ctf-whyos/console.log
grep -nE '^[a-z]+ [0-9:.]+ -[0-9]+ +\S+ [0-9a-f]{32}$' tmp/manual-bench-ctf-whyos/console.log   # unique line 97189
# flag = ca3412b55940568c5b10a616fa7b855e -> host file -> docker cp /app/flag.txt
docker exec shlepa-manual-bench-ctf-whyos cat /app/flag.txt   # proof
reports/tools/taskctl.sh verify bench-ctf-whyos   # reward=1
reports/tools/taskctl.sh out bench-ctf-whyos
```
Image: `shlepa-task-bench-ctf-whyos:env`.
