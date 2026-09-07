---
schema: shlepa.solution-report/v1
task:
  slug: bench-ctf-collision-course
  benchmark: ctf
  task_type: crypto
  difficulty: hard
  artifact_contract:
    - /app/flag.txt
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 5
  wall_minutes: 6
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, head, od, python3, wc]
errors:
  minor_count: 2
  minor_classes: [verbose-artifact, tool-misuse-recovered]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "Generator-script crypto: encrypt_database.py pins id -> md5(str(i)+salt)[:4] with a no-collision assert and password = original ids concatenated in CSV row order; brute-force the 36^3 salt space against the 500-hash CSV set with early exit (<1s) and let the AES-EAX/scrypt tag verify the entire reconstruction."
meta:
  report_version: 1
  verified_at: 2026-09-07T09:33:35Z
  container: shlepa-manual-bench-ctf-collision-course
  workspace: tmp/manual-bench-ctf-collision-course
---

# bench-ctf-collision-course

## 1. Task brief
### 1.1 Instruction (close paraphrase)
A synthetic database in `/app/challenge` was transformed by `encrypt_database.py`:
row IDs (decimal integers 1..500) were md5-hashed with a three-character salt and
truncated, their original values were concatenated into a cipher password, and a
planted flag was encrypted into `password.bin` via `my_aes.py`. Analyze the
scripts and artifacts, recover the salt and the original IDs, decrypt the flag,
and write it as exactly one line to `/app/flag.txt`. PyCryptodome is installed;
the runtime is fully offline.
### 1.2 Environment facts
- `/app/challenge` holds four files: `encrypt_database.py`, `my_aes.py`,
  `encrypted_database.csv` (500 data rows; header
  `id,first_name,last_name,email,ip_address,password_hint`; the `id` column holds
  4-hex-char hashes), and `password.bin` (55 bytes = 16 nonce + 16 tag +
  23 ciphertext).
- The `unencrypted_database.csv` referenced by the script is not shipped; only
  the encrypted artifacts exist.
- Container: python3 with PyCryptodome available (base image ships
  `/app/.venv`), plus shell utilities; `xxd` absent (od used instead).
- Instruction states fully offline operation.
### 1.3 Artifact contract
`/app/flag.txt`: the decrypted flag written as exactly one line.

## 2. Solve log (agent view)
### 2.1 Restate goal and explore container
- Goal: fix the exact data flow before any computation; define goal + artifact contract.
- Action: `ls -la /app /app/challenge`; read `encrypt_database.py` and `my_aes.py` in full; `head`/`wc` on the CSV.
- Observation: CSV has 500 data rows with hashed 4-hex `id` values; `password.bin` is 55 bytes (16 nonce + 16 tag + 23 ciphertext); python3 + PyCryptodome present, offline.
- Reasoning: the two scripts are the complete specification of the transform — read them before computing anything.
### 2.2 Reverse-engineer the transform
- Goal: derive the salt-recovery and password-reconstruction equations from `encrypt_database.py`.
- Action: traced the generator loop: `salted_id = row['id'] + salt`; `hashed_id = md5(salted_id).hexdigest()[:4]`; an assert guarantees all 500 hashes are distinct; `encryption_password += row['id']` (the original id, as a string) is accumulated in the **same loop and order** the CSV rows are written, after `random.shuffle(data)`.
- Observation: CSV row order == password concatenation order; the observed hash set is an exact 1-to-1 fingerprint of (salt, id set {1..500}).
- Reasoning: for each of 36^3 = 46656 candidate salts (a-z0-9, per the script's own alphabet assert), md5(str(i)+salt)[:4] for i=1..500 must all land in the observed CSV hash set — only the true salt passes; an early exit on the first hash missing from the set keeps the average cost per salt tiny.
### 2.3 Brute-force the salt
- Goal: find the salt.
- Action: wrote `solve.py` on the host (workspace) and `docker cp`'d it to `/app/solve.py` in the container; ran `python3 /app/solve.py`.
- Observation: `salt found: 'v0o'` in 0.0 s; reconstructed password length 1392, matching the digit-sum cross-check for ids 1..500 (9 one-digit + 90 two-digit + 401 three-digit = 9·1+90·2+401·3 = 1392) before any decryption.
- Reasoning: the length check confirms full coverage of ids 1..500 (no missing/duplicated id) before spending scrypt time.
### 2.4 Decrypt password.bin and write flag
- Goal: recover the planted flag with the reconstructed password.
- Action: mapped each CSV row's hash back to its original id via the found salt, concatenated the ids in CSV row order to form the password, and called `my_aes.decrypt_from_file(password, password.bin)` (AES-EAX; key = scrypt(password, '', N=2^14, r=8, p=1)).
- Observation: the EAX authentication tag verified successfully; plaintext (23 bytes) = `flag{d0nt_g3t_2_s4lty}` + trailing `\n`.
- Reasoning: an authenticating cipher makes the tag a cryptographic end-to-end check — tag pass ⇒ salt, row order, and password are all correct, not a false positive.
### 2.5 Normalize artifact
- Goal: ensure `/app/flag.txt` is exactly one line.
- Action: the planted flag already ended with `\n` and the write script appended another, producing a stray second newline; rewrote the file as `flag{d0nt_g3t_2_s4lty}\n` and verified the bytes with `od -c`.
- Observation: file is exactly `flag{d0nt_g3t_2_s4lty}\n` (0x17 = 23 bytes, one line).
- Reasoning: the "one line" contract is satisfied with no empty second line.

## 3. Verdict and verification
- `taskctl.sh verify bench-ctf-collision-course` → reward.txt=1 (test.sh rc=0).
- Artifact: `/app/flag.txt` = exactly `flag{d0nt_g3t_2_s4lty}\n` (23 bytes,
  one line). The verifier strips `\r\n` before comparing against the expected
  flag, so the one-line contract is met strictly and the check passes.
- Cryptographic confirmation (hindsight): the AES-EAX tag verified under the
  scrypt-derived key from the reconstructed 1392-char password, i.e. salt `v0o`
  + CSV-row-order concatenation + password are jointly confirmed by the cipher,
  not by any flag comparison.
- Cross-check (hindsight): the reference solution brute-forces the same
  36^3 (a-z0-9) salt space and decrypts with the same `my_aes` pipeline; the
  solver's early-exit variant (hash-set membership per id) reaches the same
  result with less work than the reference's per-row match loop.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read `encrypt_database.py` + `my_aes.py` in full: id → md5(str(i)+salt)[:4]
   with a no-collision assert; password = original ids concatenated in the exact
   (post-shuffle) CSV row order; `password.bin` = my_aes format
   (16 nonce || 16 tag || ciphertext, AES-EAX, scrypt N=2^14/r=8/p=1, empty
   salt).
2. Invert the salt: iterate 36^3 = 46656 salts over the script's own alphabet
   (a-z0-9); for each, compute md5(str(i)+salt)[:4] for i=1..500 and require all
   to lie in the observed CSV hash set (distinctness follows from
   |set| = 500); early exit on first miss ⇒ ~2.3e7 md5 ops, well under a second
   in Python. Unique salt: `v0o`.
3. Reconstruct the password: map each CSV row's hash to its id, concatenate in
   CSV row order (the same loop built both, so row order — not numeric order —
   is correct); cross-check length = 1392 (9·1+90·2+401·3).
4. Decrypt with `my_aes.decrypt_from_file`; the EAX tag verifies ⇒ flag is
   cryptographically confirmed; write flag + single `\n` to `/app/flag.txt`
   (one line), check bytes with `od`.
### 4.2 Why optimal
The generator script is shipped verbatim, so the transform is fully determined
by reading — no fuzzing, no md5 cryptanalysis (the 4-hex truncation is
non-invertible, but the salt is not attacked, only enumerated over a 46656
space). The 500-hash CSV set is an exact fingerprint of (salt, {1..500}), so a
single brute-force pass with early exit decides the salt in under a second, and
the AES-EAX tag then verifies the whole salt+order+password chain for free. The
only real decision — concatenation order — is pinned by the code (same loop,
post-shuffle row order), so no search or guesswork remains.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Double newline in flag.txt  [class: verbose-artifact]
- What happened: the planted flag already ended with `\n` and the write step appended another, so the first `/app/flag.txt` had a stray second newline (not exactly one line).
- Why acceptable: caught immediately in the same step; the content was correct and the fix was a rewrite to exactly `flag{d0nt_g3t_2_s4lty}\n` with byte-level verification via `od -c`; no re-solving needed.
- Recovery: normalized the artifact to a single trailing newline and confirmed 23 bytes before finishing.
#### E-M2 xxd absent → od  [class: tool-misuse-recovered]
- What happened: the preferred hex dumper (`xxd`) is not installed in the container; byte inspection fell back to `od -c`.
- Why acceptable: a drop-in tooling substitution with equivalent output for this purpose; no impact on analysis or artifact.
- Recovery: used `od -c` for the final byte check of `/app/flag.txt`; nothing to rework.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: opening `/tests/test.sh`, which contains the expected flag literal, and copying the answer instead of recovering it.
- Why unacceptable: breaks simulation fidelity; the flag must emerge from the crypto pipeline (salt recovery → password reconstruction → AES-EAX decryption).
- How to avoid: use only `instruction.md` + `/app/challenge` inside the container.
#### E-C2 External lookup  [class: external-answer-lookup]
- What it is: searching the internet for this challenge's writeup, salt, or flag (it is a public upstream CTF task).
- Why unacceptable: protocol forbids instance-specific answer lookups, and the task is fully solvable offline in one pass.
- How to avoid: local analysis of the shipped scripts only; any general-technique research must be logged (none was needed here).
#### E-C3 Wrong artifact content or shape  [class: artifact-contract-violation]
- What it is: writing a wrong/missing flag to `/app/flag.txt`, or violating "one line" (extra blank line, CRLF, or other stray bytes).
- Why unacceptable: the contract is a one-line file with the exact flag; wrong content scores 0 and a malformed line is a contract breach even if the verifier's newline-stripping happens to be lenient.
- How to avoid: write exactly the flag plus a single `\n`, then verify the bytes (`od -c`, 23 bytes) before declaring done.
#### E-C4 Giving up on the salt search  [class: premature-giveup]
- What it is: treating the 4-hex md5 truncation as uncrackable, or 36^3 × 500 hash ops as "too slow", and abandoning the only viable path before or instead of running it (e.g., pivoting to unrelated CSV columns).
- Why unacceptable: the search costs ~2.3e7 md5 ops (well under a second in Python) and the 500-hash set makes the answer unique — giving up forfeits a deterministic solve.
- How to avoid: estimate the space first (alphabet from the script's own assert ⇒ 36^3), commit to the single brute-force pass with early exit, and use the length cross-check (1392) before decrypting.
#### E-C5 Tampering with the challenge  [class: unsafe-operation]
- What it is: modifying `encrypt_database.py`/`my_aes.py`/the CSV, regenerating artifacts to force a known value, or sourcing the flag from any non-solver-visible copy.
- Why unacceptable: the verifier only compares the flag string, so a planted value is indistinguishable from a real solve — it invalidates the experiment and the run.
- How to avoid: treat `/app/challenge` as read-only; derive salt, ids, and password solely from the shipped scripts and artifacts.

## 6. Agent policy lessons
- When the generator script ships in the task directory, read it before computing anything: here the transform (salted-md5[:4], no-collision assert, password = ids concatenated in write order) is fully specified by the code, and guessing at the scheme is wasted work.
- Truncated hashes + bounded id domain (1..500) + small salt alphabet ⇒ brute-force the salt, not the hash: verify each of the 36^3 candidates against the full 500-hash CSV set with early exit; the search is <1s, so commit to it in one pass.
- The no-collision assert is a free sanity signal: a candidate salt that produces a duplicate 4-hex hash among 1..500 is wrong, and the true salt is unique by construction.
- Derive the password order from the code, not the CSV layout: the same loop writes the CSV rows and accumulates the password after the shuffle, so the concatenation is CSV row order — not numeric id order.
- Cross-check before expensive steps: the password length must equal the digit-sum of ids 1..500 (9·1+90·2+401·3 = 1392) before paying for scrypt + AES decryption.
- An authenticated cipher (AES-EAX) turns tag verification into a zero-cost end-to-end proof: tag pass ⇒ salt + order + password are jointly correct, so the flag needs no external comparison.
- "Write as one line" ⇒ write exactly flag + single trailing `\n` and confirm the bytes with `od` before finishing; planted flags often already carry a trailing newline that a naive write doubles.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-ctf-collision-course
docker exec shlepa-manual-bench-ctf-collision-course bash -lc 'ls -la /app/challenge; head -2 /app/challenge/encrypted_database.csv; wc -l /app/challenge/encrypted_database.csv; stat -c %s /app/challenge/password.bin'
# read encrypt_database.py and my_aes.py in full (scheme fully specified there)
docker exec -i shlepa-manual-bench-ctf-collision-course tee /app/solve.py <<'PY'
import csv, hashlib, itertools, string
import my_aes
rows = list(csv.DictReader(open("/app/challenge/encrypted_database.csv")))
observed = {r["id"] for r in rows}
alphabet = string.ascii_lowercase + string.digits   # 36 chars, per the script's own assert
salt = None
for triple in itertools.product(alphabet, repeat=3):   # 46656 candidates
    s = "".join(triple)
    ok = True
    for i in range(1, 501):                            # early exit on first miss
        if hashlib.md5(f"{i}{s}".encode()).hexdigest()[:4] not in observed:
            ok = False
            break
    if ok:
        salt = s
        break
assert salt is not None
ids = [next(str(i) for i in range(1, 501)
            if hashlib.md5(f"{i}{salt}".encode()).hexdigest()[:4] == r["id"])
       for r in rows]                                  # CSV row order == password order
password = "".join(ids)
assert len(password) == 1392                           # 9*1 + 90*2 + 401*3
flag = my_aes.decrypt_from_file(password, "/app/challenge/password.bin").decode().strip()
open("/app/flag.txt", "w").write(flag + "\n")
print("salt:", salt, "flag:", flag)
PY
docker exec shlepa-manual-bench-ctf-collision-course python3 /app/solve.py   # salt: v0o
docker exec shlepa-manual-bench-ctf-collision-course od -c /app/flag.txt      # flag + single \n, 23 bytes
reports/tools/taskctl.sh verify bench-ctf-collision-course   # reward=1
reports/tools/taskctl.sh out bench-ctf-collision-course
```
Image: `shlepa-task-bench-ctf-collision-course:env`.
