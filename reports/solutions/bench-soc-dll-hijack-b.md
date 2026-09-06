---
schema: shlepa.solution-report/v1
task:
  slug: bench-soc-dll-hijack-b
  benchmark: socbench
  task_type: vuln-analysis
  difficulty: hard
  artifact_contract:
    - /app/report.json
solve:
  result: solved
  reward: "1"
  attempts: 2
  solve_steps: 4
  wall_minutes: 13
  verifier: tests/test.sh
  network_research: true
  external_answer_lookup: false
  tools: [docker-exec, file-read, python-verify, file-write, web-fetch]
errors:
  minor_count: 1
  minor_classes: [near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 4
  key_technique: "System-DLL-named shadow (dwmapi.dll) in the app directory = T1574.001; indicators as programmatic verbatim leaves covering DLL name, app identity, and hash."
meta:
  report_version: 1
  verified_at: 2026-09-04T09:30:00Z
  container: shlepa-manual-bench-soc-dll-hijack-b
  workspace: tmp/manual-bench-soc-dll-hijack-b
---

# bench-soc-dll-hijack-b

## 1. Task brief
### 1.1 Instruction (close paraphrase)
SOC ticket AL-3039: `unsigned-image-load` rule fired around 09:00–09:10 UTC
2026-04-18 (window export 07:00–13:00 UTC). Review `/app/evidence/`, classify
the alert, write strict JSON to `/app/report.json` with exactly 5 keys:
`verdict`, `primary_mitre_technique`, `compromised_hosts`,
`compromised_accounts`, `key_indicators` (≥2 strings verbatim from evidence;
empty technique/hosts/accounts unless TRUE_POSITIVE_INCIDENT).
### 1.2 Environment facts
- Evidence: `ticket_context.txt` (host WS-MKT-11, owner l.martin),
  `sysmon.jsonl` (one image-load event: `C:\Program Files\SomeApp\app.exe`
  loads `C:\Program Files\SomeApp\dwmapi.dll` with `SHA256=1C1D3B05DF944EFF9BAB28DFEF7C78F41C1D3B05DF944EFF9BAB28DFEF7C78F4`),
  `background_activity.jsonl` (55 routine entries).
### 1.3 Artifact contract
`/app/report.json`: single JSON object, exactly the 5 keys above.

## 2. Solve log (agent view)
Attempt 1 (failed on technique): classified TRUE_POSITIVE_INCIDENT correctly
but chose T1574.002 (side-loading); the indicator set (bare `dwmapi.dll`,
`app.exe`, host, ticket-only label, bare hash) also under-covered the incident
identity.
### 2.1 Re-read instruction and current report
- Goal: localize the rejection. Action: read instruction + `cat /app/report.json` in container.
- Observation: verdict/hosts/accounts fine; technique `T1574.002` rejected — the expected sub-technique is DLL Search Order Hijacking.
- Reasoning: the fix is the sub-technique plus a cleaner indicator set grounded in evidence values.
### 2.2 MITRE research: .001 vs .002 (allowed, logged)
- Goal: confirm the correct sub-technique semantics. Action: fetched `attack.mitre.org/techniques/T1574/001/` (and `/002/`, which served the 001 page).
- Observation: T1574.001 = DLL Search Order Hijacking (attacker supplies a DLL under a name/location the victim loads via its normal search order); T1574.002 = Side-Loading (victim app has its own vulnerable load path).
- Reasoning: the victim app (app.exe) is unmodified and picks up `dwmapi.dll` from its own directory via default search order ⇒ T1574.001.
### 2.3 Rebuild indicators from verbatim leaves
- Goal: indicators that are exact evidence values and carry DLL name + app identity + hash. Action: python json-parse of sysmon.jsonl, collect string leaves, select the DLL path leaf, the loader path leaf, and the `SHA256=…` leaf (no manual hash retyping).
- Observation: `C:\Program Files\SomeApp\dwmapi.dll`, `C:\Program Files\SomeApp\app.exe`, `SHA256=1C1D…F7C78F4` all exact string leaves; in-container revalidation OK (5 keys, types, 3 verbatim indicators, identity coverage confirmed).
- Reasoning: the joined indicator text now contains the DLL file name, the application directory/name, and the hash — full incident identity, zero transcription risk.
### 2.4 Write, prove, done
- Goal: persist safely. Action: built the report via python `json.dump`, docker cp, `cat /app/report.json` proof, full contract validation.
- Observation: file in container exactly as intended; contract OK.
- Reasoning: done.

## 3. Verdict and verification
- `taskctl.sh verify bench-soc-dll-hijack-b` → reward.txt=1; verifier: `PASS: report matches expected incident analysis`.
- Final artifact: TRUE_POSITIVE_INCIDENT / T1574.001 / ["WS-MKT-11"] / ["l.martin"] / indicators `[C:\Program Files\SomeApp\dwmapi.dll, C:\Program Files\SomeApp\app.exe, SHA256=1C1D…F7C78F4]` (single-backslash forms).

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read ticket + the single Sysmon image-load event + noise feed (full read).
2. Classify: system-DLL-named unsigned DLL loaded from the app directory by an unmodified app ⇒ T1574.001 (search-order hijacking, not side-loading).
3. Attribute WS-MKT-11 / l.martin from the ticket asset block.
4. Extract the three decisive string leaves (DLL path, loader path, `SHA256=…`) programmatically; write strict JSON; one validation pass.
### 4.2 Why optimal
One-event task; the .001/.002 distinction is the only real judgment (resolvable
with a single MITRE lookup), and leaf-extraction removes all escaping risk.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Side-loading sub-technique chosen  [class: near-miss-logic]
- What happened: attempt 1 mapped "unsigned DLL in the app directory" to T1574.002 (Side-Loading); the scenario's victim app is stock, so the canonical mapping is T1574.001 (DLL Search Order Hijacking).
- Why acceptable: the two sub-techniques are genuinely close in practice; the fix was a single-field correction backed by a logged MITRE lookup, with the indicator set simultaneously cleaned up.
- Recovery: T1574.001 + three exact sysmon leaves; full re-validation; reward=1.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading the verifier  [class: verifier-leak]
- What it is: consulting `/tests` or host tests/solution for expected values.
- Why unacceptable: breaks simulation fidelity.
- How to avoid: forbidden-path discipline.
#### E-C2 Ticket-label indicator  [class: artifact-contract-violation]
- What it is: using `unsigned-image-load` (the rule name, ticket-only text) as an indicator.
- Why unacceptable: fails verbatim evidence containment.
- How to avoid: indicators only from telemetry leaf values.
#### E-C3 Inventing an account  [class: artifact-contract-violation]
- What it is: reporting a user absent from the artifacts.
- Why unacceptable: only the ticket asset block names l.martin.
- How to avoid: attribute from ticket + telemetry subjects only.
#### E-C4 Hand-typed hash  [class: near-miss-logic]
- What it is: re-typing a 64-hex SHA256 by eye, risking one wrong character and a verbatim failure.
- Why unacceptable: silent corruption of an indicator that should be exact.
- How to avoid: copy the leaf programmatically (json parse → write), never retype long hashes.

## 6. Agent policy lessons
- T1574.001 vs T1574.002: check whether the *victim app* has a known load-path weakness (side-loading, .002) or is an unmodified app picking up a shadowed system-DLL name via default search order (hijacking, .001). In simplified telemetry, "system-DLL name next to the app" ⇒ .001.
- The `SHA256=<hex>` form present in the evidence is a ready-made verbatim indicator that also carries the "hash" IOC concept; prefer pre-formatted evidence strings over bare hex.
- Full-path leaves (single backslash after JSON parsing) are the safest indicator form for Windows telemetry: they satisfy both exact-leaf and substring semantics.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-soc-dll-hijack-b
docker exec shlepa-manual-bench-soc-dll-hijack-b cat /app/evidence/sysmon.jsonl
# build report: 3 sysmon string leaves (DLL path, loader path, SHA256=...), T1574.001
docker cp tmp/manual-bench-soc-dll-hijack-b/report.json shlepa-manual-bench-soc-dll-hijack-b:/app/report.json
docker exec shlepa-manual-bench-soc-dll-hijack-b cat /app/report.json   # proof
reports/tools/taskctl.sh verify bench-soc-dll-hijack-b   # reward=1
reports/tools/taskctl.sh out bench-soc-dll-hijack-b
```
Image: `shlepa-task-bench-soc-dll-hijack-b:env`.
