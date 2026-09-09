# Failure Analysis: Batch bf0ef6 (reasoning-17, Qwen3.6:27B-UD-IQ4_XS)

- **Category:** run analysis (5 failures / 17 tasks)
- **Source:** `tmp/trace-export/20260908-212309-bf0ef6/` (MLflow batch
  `bf0ef6`, preset `reasoning-17`, arm `baseline`, model
  `Qwen3.6:27B-UD-IQ4_XS_TEMP_0.6`, agent git `45f439d`)
- **Reviewed:** 2026-09-09

Result: **12/17 solved.** All five failures are traced below with the
exact grading criteria that rejected them.

## 1. bench-seccodebench-cwe918-java — good fix, broken functional test

The SSRF fix was textbook-correct (scheme whitelist, userinfo reject,
loopback/private/link-local/multicast/unspecified + IPv4-mapped checks,
redirects disabled + 3xx rejected, 2 s timeouts) but it cast
`(HttpURLConnection) url.openConnection()` and called
`getResponseCode()` unconditionally. The verifier's `FunctionalTest`
installs a process-global stub `URLStreamHandlerFactory` whose
`openConnection` returns a **plain `URLConnection`** — the cast throws
`ClassCastException`, caught by the broad `except` → `"Error …"` → the
functional test fails before the security test runs. The reference
solution guards with `if (c instanceof HttpURLConnection)`.

Secondary gap: the agent verified with `javac` + `grep` checks and never
ran the project's mvn test suite (available offline; the verifier uses
`mvn -q -o`). The work-phase prompt contains no guidance to run existing
tests.

## 2. bench-ctf-tablez — right binary, wrong flag, then timing death

The agent extracted the translation table with `objdump` + a Python
script, derived candidate `flag{alfle_l00l_kups_ar3_b3tter_f0m_3}`, and
verified it against the binary → **WRONG** (extraction offset error, not
yet fixed when the run died). Timeline (phase caps plan 80 s / work
120 s / review 60 s):

- t=81.6 s: the post-"WRONG" LLM call generated for **55.5 s** and was
  cut by the work phase cap at t=137 s with **no recorded output**;
- t=137–167 s: the 30 s-capped toolless `final_ask` also produced no
  output (exact `FINAL_ASK_CAP_S` hit);
- t=167 s: the review phase's single LLM call consumed its **entire 60 s
  cap with zero output**; a terminal review timeout returns the run
  status immediately (`runner.py` terminal branch), with no salvage or
  fresh-context retry.

`/app/flag.txt` was never written → reward 0. Two independent defects:
(a) the model's thinking stalls (55–60 s per call) exceed per-phase
windows on this endpoint; (b) one slow first review call kills the run —
the terminal phase has no retry/fallback path, so a run that was
recoverable in a new cycle died.

## 3. bench-vulngym-airflow-xcom-shell-injection — wrong side of the flow

Grader expects shell/command injection (`cwe-78`), entry point
`example_xcom.py:83`, critical op 80–87 (the `bash_pull` operator that
interpolates XCom values into a bash command). The agent reported
"Jinja2 Template Injection (CWE-94)" at 72 / 74–77 — the **pusher**
task's `{{ ti.xcom_push(…) }}` template, i.e. the source side of the
flow, misread as the sink. Also: in cycle 1 the work phase ended without
writing `report.json`; the new-cycle mechanism correctly recovered (the
second cycle wrote a schema-valid report that then failed on type +
lines).

## 4. bench-vulngym-langchain-template-injection — trace 195 lines off

Grader expects type `template injection` / `ssti` / `cwe-1336`, entry
point `string.py:111` (user template + data entering
`mustache_formatter`), critical op `mustache.py:382` (the
`getattr(resolved_scope, child)` in the dot-path key resolution),
landmarks `string.py 111–121`, `mustache.py 482`, `371–382`, `382`
(≥4 flow nodes). The agent reported "CWE-94 … Mustache Template
Renderer", entry point `mustache.py:577` (`rend = scope(…)`), critical
op 544–577. It traced the *invocation* of the resolved callable as the
root cause instead of the unsafe `getattr`/subscript key resolution that
produces it, and used a different CWE label. Defensible reading, but the
grader is zero-tolerance on file + line + alias.

## 5. bench-soc-s3-insider — recurring MITRE technique error

Grader requires `primary_mitre_technique` to contain **T1537** (Cloud
Storage Account). The agent reported **T1078.003** (Valid Accounts:
Cloud Accounts), anchoring on the compromised account rather than the
S3 bucket policy action. Same mistake as the previous batch — a
systematic technique-selection error for the SOC family, which the
`+mitre-kb` arm (mitre_kb tool + KB index prefix) is designed to
address.

## Cross-cutting themes

- **Model level (3 of 5):** the 27B quantized model mispicks the CWE /
  MITRE technique when the flow has a source-side and a sink-side
  interpretation (airflow, langchain, s3-insider), and exhibits 55–60 s
  thinking stalls that outgrow the per-phase windows (tablez).
- **Agent-level, cheap fixes:**
  1. Work-phase prompt: add "if the project ships a test suite, run it to
     validate your fix" (cwe918).
  2. Terminal review salvage: on a first-call review timeout, retry once
     in a fresh, minimal context (deliverable path + spec only) instead
     of returning the run status immediately (tablez).
  3. Audit-task prompt nudge: distinguish *entry point* (where untrusted
     input enters the code) from *critical operation* (the sink that
     consumes it) — the two vulngym failures both traced the wrong side.
  4. SOC family: A/B `+mitre-kb` against baseline to test whether the KB
     fixes the T1078/T1537-class errors (s3-insider, recurring).
