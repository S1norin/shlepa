---
schema: shlepa.solution-report/v1
task:
  slug: contest-find-ssrf-go
  benchmark: contest
  task_type: audit
  difficulty: medium
  artifact_contract:
    - /app/security_report.json
solve:
  result: solved
  reward: "1"
  attempts: 1
  solve_steps: 5
  wall_minutes: 4
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, grep, python3]
errors:
  minor_count: 2
  minor_classes: [over-exploration, near-miss-logic]
  fatal_occurred: false
  fatal_classes: []
ideal:
  ideal_steps: 3
  key_technique: "Full read of the 26-line source → pin validation (line 11) and sink (http.Get, line 14) with grep -n → single CWE-918 SSRF finding with two concrete bypasses (direct private-IP URL, 302→internal redirect chain) and a repair covering host allowlist, resolved-IP rejection, dial pinning, and CheckRedirect re-validation."
meta:
  report_version: 1
  verified_at: 2026-09-06T18:43:35Z
  container: shlepa-manual-contest-find-ssrf-go
  workspace: tmp/manual-contest-find-ssrf-go
---

# Solution report: contest-find-ssrf-go

## 1. Task brief (agent view)
### 1.1 Instruction (close paraphrase)
Review the Go source under `/app/src/` of a deliberately small "link-card"
service; it contains exactly one planted security logic defect. **Do not
modify the application.** Deliverable: `/app/security_report.json` — a JSON
object with a non-empty `findings` array; each finding carries `title`,
`severity`, `category`, `location`, `evidence`, `impact`, `recommendation`
(all non-empty strings). The report must identify the applicable CWE, the
affected handler and sink, a concrete bypass of the existing validation, the
impact, and a repair that covers redirects and resolved IP addresses.
### 1.2 Environment facts
- Only application file is `/app/src/main.go` (26 lines); no `go.mod`, no
  other handlers, `main()` is empty, no service listening — a pure static-audit
  target.
- The rest of `/app` is a Python `.venv` (tooling noise, usable for JSON
  validation).
### 1.3 Artifact contract
`/app/security_report.json`: strictly valid JSON object, non-empty
`findings` array, each element with the 7 required string fields; content must
name the CWE, handler + sink, a concrete bypass of the existing validation,
the impact, and a repair that explicitly covers both redirects and resolved
IP addresses.

## 2. Solve log (agent view)
### 2.1 Restate goal + artifact contract
- Goal: Audit the Go source under /app/src/ of a small "link-card" service; find the one planted security logic defect.
- Action: Read instruction.md.
- Observation: Artifact = /app/security_report.json, JSON object with non-empty `findings` array; each finding needs `title`, `severity`, `category`, `location`, `evidence`, `impact`, `recommendation` (all non-empty strings). Must identify CWE, affected handler, sink, concrete bypass of existing validation, impact, and a repair covering redirects AND resolved IP addresses.
- Reasoning: This shapes the report fields: category should carry the CWE id, location should name handler + sink + line, evidence should carry a concrete bypass, recommendation must mention both redirects and resolved IPs.
### 2.2 Explore container
- Goal: Find the application source.
- Action: `docker exec ... find /app -type f` (top), `ls /app/src/`.
- Observation: Only application file is `/app/src/main.go` (rest of /app is a Python .venv). No go.mod, no other handlers; `main()` is empty.
- Reasoning: Single file, single defect to find.
### 2.3 Read the source
- Goal: Identify the planted defect.
- Action: `docker cp` main.go to /tmp and read it (26 lines).
- Observation: `fetchCard(rawURL)` validates only `strings.HasPrefix(rawURL, "https://")` (line 11), then calls `http.Get(rawURL)` (line 14) — the default client with no host/IP checks and default redirect following.
- Reasoning: Classic SSRF (CWE-918): the prefix check is a bypass-able validation, not a destination constraint. Any `https://<internal>` URL passes (e.g. `https://169.254.169.254/latest/meta-data/`, `https://127.0.0.1/...`), and the default client follows up to 10 redirects without re-validation, so an allowed host can 302 to an internal/http:// URL.
### 2.4 Confirm line numbers + write report
- Goal: Produce /app/security_report.json with exact handler/sink locations.
- Action: `grep -n` to confirm line 11 (validation) and line 14 (sink `http.Get`); wrote security_report.json on host and `docker cp` into the container.
- Observation: Report written, 2850 bytes, 1 finding. Fields: title (SSRF in fetchCard), severity "high", category "server-side request forgery (SSRF), CWE-918", location naming fetchCard() + line 11 validation + line 14 sink, evidence with two concrete bypasses (direct private-IP fetch; 302 redirect to `http://169.254.169.254/...` followed by default client), impact (metadata/credential theft, internal probing, segmentation bypass), recommendation covering url.Parse + host allowlist, pre-connect DNS resolution with private/reserved-IP rejection (IPv4+IPv6 ranges), DialContext IP pinning against DNS rebinding, and CheckRedirect re-validation of scheme+host+resolved-IP on every hop (no http:// downgrade).
- Reasoning: The instruction's "repair that covers redirects and resolved IP addresses" is satisfied explicitly in the recommendation; single finding matches "one planted security logic defect".
### 2.5 Validate artifact
- Goal: Ensure the JSON is well-formed and satisfies the field contract.
- Action: `docker exec ... /app/.venv/bin/python3` script asserting `findings` non-empty and all 7 fields are non-empty strings.
- Observation: `OK 1 finding(s), all 7 fields non-empty strings; bytes: 2850`.
- Reasoning: Artifact contract satisfied; no other deliverables required.

## 3. Verdict and verification
- `taskctl.sh verify contest-find-ssrf-go` → reward.txt=1 (test.sh rc=0,
  `python3 /tests/verify.py` exit 0).
- Verifier assertions all satisfied by the single finding: JSON parses;
  CWE-918/SSRF keyword present; handler/sink named (`fetchCard`, `http.Get`,
  `rawURL`); private/metadata target language present; "redirect" covered;
  resolved-IP/DNS language present.
- Artifact check: `/app/security_report.json` = 2850 bytes, 1 finding, all 7
  fields non-empty; mirrored at `tmp/manual-contest-find-ssrf-go/app/`.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction.md; restate the strict 7-field JSON contract and the
   content requirements (CWE, handler, sink, concrete bypass, repair covering
   redirects and resolved IPs).
2. Read the entire 26-line `main.go` (the whole reconnaissance) and pin exact
   line numbers with `grep -n` — validation at line 11, sink at line 14.
3. Emit one high-severity CWE-918 finding: scheme-only validation before
   default `http.Get`; evidence = direct `https://169.254.169.254/...` plus a
   302→internal redirect chain; recommendation = strict parse + host allowlist,
   pre-connect resolved-IP rejection, dial pinning, per-hop `CheckRedirect`
   re-validation; `json.load`-validate before delivery.
### 4.2 Why optimal
Single 26-line file ⇒ full read IS the audit; no service runs, so live PoCs
are impossible and unnecessary — written concrete bypasses satisfy the
evidence requirement. One finding matches "one planted defect"; filler
findings add length, not score. The verifier keys on keyword coverage of the
contract requirements, so mirroring the instruction's wording (redirects,
resolved IPs) into the fields is what wins.
### 4.3 Estimated ideal steps: 3

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Assumed a full service and listed .venv noise  [class: over-exploration]
- What happened: initially assumed "the service" implied a multi-file
  deployment; spent a couple of listing calls on the /app tree before
  discovering the app is one 26-line file and the rest is .venv tooling.
- Why acceptable: exploration was bounded (a few quick commands) and the true
  scope was established within the same step.
- Recovery: pivoted immediately to the single file (`/app/src/main.go`); no
  further wasted enumeration.
#### E-M2 Imprecise initial line-number guess  [class: near-miss-logic]
- What happened: first recorded the validation/sink lines as 14/16 from a
  visual read of the file; the correct references are line 11 (validation) and
  line 14 (`http.Get`).
- Why acceptable: the defect identification itself was correct; only the
  line references were off.
- Recovery: re-verified with `grep -n` (validation line 11, sink line 14)
  before writing the report, so the delivered artifact carries exact locations.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Modifying the application  [class: constraint-violation]
- What it is: "fixing" the SSRF in `main.go` while auditing — the instruction
  explicitly forbids modifying the application.
- Why unacceptable: the deliverable is the report; changed source invalidates
  the audit target and the verifier's environment.
- How to avoid: read-only interaction with the app; write only the artifact.
#### E-C2 Invalid JSON or missing required fields  [class: artifact-contract-violation]
- What it is: comments/trailing commas/unclosed strings, or a finding missing
  any of the 7 required fields.
- Why unacceptable: the verifier parses the file strictly and asserts the
  structure; malformed JSON or empty fields = reward 0 regardless of quality.
- How to avoid: build the JSON carefully and assert-parse it (`json.loads` +
  non-empty field check) before delivery.
#### E-C3 Vague finding missing contract specifics  [class: artifact-contract-violation]
- What it is: a finding that omits the CWE id, the handler/sink, a concrete
  bypass, or the redirect/resolved-IP repair language.
- Why unacceptable: the verifier keyword-checks the finding text for exactly
  these elements (CWE-918/SSRF, fetchCard/http.Get, private/metadata target,
  redirect, resolved-IP/DNS); missing any of them fails even a well-written
  JSON file.
- How to avoid: mirror the instruction's content requirements verbatim into
  the fields (category carries the CWE, location names handler + sink + line,
  evidence carries a concrete bypass, recommendation covers both redirect
  re-validation and resolved-IP checks).
#### E-C4 Looking up this task's specific answer  [class: external-answer-lookup]
- What it is: searching the internet for the expected CWE/finding for this
  task instance.
- Why unacceptable: protocol breach — the solve must come from the container
  contents; it invalidates the report's faithfulness.
- How to avoid: general technique research only, always logged; the answer is
  fully derivable from the 26-line source.
#### E-C5 Reading the verifier or reference solution  [class: verifier-leak]
- What it is: opening `tests/**` or `solution/**` during the solve to learn
  expected values or the check's keywords.
- Why unacceptable: it contaminates the agent-view solve log and the error
  analysis; reports must reflect what an agent could derive from its own
  environment.
- How to avoid: the solver's forbidden paths are tests/solution/upstream/
  research/reports; only the parent reads them, after the solve.
#### E-C6 Firing live requests at internal/metadata endpoints  [class: unsafe-operation]
- What it is: actually curling `169.254.169.254` or scanning internal hosts
  to "prove" the SSRF in a static-audit task where nothing runs.
- Why unacceptable: out of scope for a read-only audit, potentially harmful
  side effects, and unnecessary — the contract asks for concrete written
  bypasses, not executed ones.
- How to avoid: demonstrate the bypass by construction (exact URL + redirect
  chain) citing the sink's default redirect behavior.

## 6. Agent policy lessons
- For "deliberately small" audit tasks, a full source read is the entire
  reconnaissance — enumerate files first, confirm the true app scope, and do
  not assume a multi-service architecture from the word "service".
- When the instruction enumerates content requirements (CWE, handler, sink,
  concrete bypass, redirect repair, resolved-IP repair), mirror each one
  verbatim into the corresponding field; graders keyword-check the finding
  text against those requirements.
- Never cite line numbers from a visual read — confirm with `grep -n` before
  they enter the artifact; near-miss references erode triage trust.
- Static audit with no running service: "concrete evidence" means a specific
  attacker URL + redirect chain written down, not an executed PoC.
- "One planted defect" ⇒ exactly one sharp finding; extra filler findings add
  length, not score, and dilute the report.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up contest-find-ssrf-go
docker exec shlepa-manual-contest-find-ssrf-go find /app -type f -not -path '*/.venv/*'   # → /app/src/main.go
docker exec shlepa-manual-contest-find-ssrf-go grep -n . /app/src/main.go   # line 11 = https:// prefix check, line 14 = http.Get(rawURL)
# write /app/security_report.json (1 finding, 7 fields) on host, then:
docker cp security_report.json shlepa-manual-contest-find-ssrf-go:/app/security_report.json
docker exec shlepa-manual-contest-find-ssrf-go /app/.venv/bin/python3 -c "import json;d=json.load(open('/app/security_report.json'));fs=d['findings'];assert fs and all(f[k] for f in fs for k in ['title','severity','category','location','evidence','impact','recommendation']);print('OK')"
reports/tools/taskctl.sh verify contest-find-ssrf-go    # reward=1
reports/tools/taskctl.sh out contest-find-ssrf-go       # mirrors /app → tmp/manual-contest-find-ssrf-go/app
reports/tools/taskctl.sh down contest-find-ssrf-go
```
Image: `shlepa-task-contest-find-ssrf-go:env`.
