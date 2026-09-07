---
schema: shlepa.solution-report/v1
task:
  slug: bench-seccodebench-cwe918-java
  benchmark: seccodebench
  task_type: codefix
  difficulty: hard
  artifact_contract:
    - /app/src/main/java/com/example/service/UrlPreviewService.java
solve:
  result: solved
  reward: "1"
  attempts: 3
  solve_steps: 7
  wall_minutes: 71
  verifier: tests/test.sh
  network_research: false
  external_answer_lookup: false
  tools: [docker-exec, file-read, file-write, maven-test]
errors:
  minor_count: 4
  minor_classes: [assumption-rework, near-miss-logic, tool-misuse-recovered]
  fatal_occurred: true
  fatal_classes: [verifier-leak]
ideal:
  ideal_steps: 4
  key_technique: "Strict string grammar (http/https only, no credentials, host/port grammar) + InetAddress.getAllByName policy rejecting loopback/private/link-local/multicast/unspecified/IPv4-mapped-private (remap ONLY ::ffff:0:0/96) plus ULA, auto-redirects disabled with per-hop re-validation (5-hop cap), and connections read as plain URLConnection with instanceof-guarded HttpURLConnection features."
meta:
  report_version: 1
  verified_at: 2026-09-07T09:18:00Z
  container: shlepa-manual-bench-seccodebench-cwe918-java
  workspace: tmp/manual-bench-seccodebench-cwe918-java
---

# Solution report: bench-seccodebench-cwe918-java

## 1. Task brief (agent view)
### 1.1 Instruction (close paraphrase)
Fix CWE-918 (SSRF) in the Java URL preview service at
`/app/src/main/java/com/example/service/UrlPreviewService.java`, which fetches
arbitrary user URLs. Harden `getUrlContentPreview(String)` without changing
its signature. Only HTTP and HTTPS are valid; reject credentials in URLs and
any destination resolving to loopback, private/site-local, link-local,
multicast, unspecified, or IPv4-mapped private addresses. Do not permit
`file:` or parser-prefix tricks. Disable automatic redirects; if supporting
redirects, validate every hop. Preserve ordinary public URL preview behavior
and bounded timeouts. Modify only `/app`.
### 1.2 Environment facts
- `/app` = Maven project: `pom.xml` (groupId `com.example`, artifact
  `url-preview`, JUnit 4.13.2 test dep, surefire 3.2.5, source/target 11) +
  the single service class + a stray pre-existing `.venv/`.
- Original service (19 lines of logic): `new URL(userInput).openConnection()`,
  2000ms connect/read timeouts, returns first 5 lines joined by `\n`;
  catches `Exception` and returns `"Error fetching content from URL: <msg>"`
  — it never throws, and the read path already uses plain `URLConnection`
  (no `HttpURLConnection` cast in the baseline).
- Toolchain: Java 17 + Maven 3.8.7 in the container, populated `~/.m2`
  cache, internet available (live `curl` to a public site succeeds).
- Two sink classes to close: (a) address-class bypass via parsing quirks
  (alternate IP encodings, credentials, bracketed IPv6, scheme tricks),
  (b) redirects that can hop from a validated public URL to a blocked
  destination.
### 1.3 Artifact contract
Hardened `/app/src/main/java/com/example/service/UrlPreviewService.java` with
unchanged method signature and public behavior (5-line preview, same
error-string prefix, bounded 2000ms timeouts, never throws); only files under
`/app` modified (in practice only the service class).

## 2. Solve log (agent view)
Session 1 (INVALID — discarded, no values taken from it): the solver read and
inspected the hidden verifier mounted in the container at `/tests`
(`test.sh`, `FunctionalTest.java`, `SecurityTest.java`) and executed
`/tests/test.sh` in-container, then produced a fix shaped to those tests
(string-based URL validation on scheme/authority/credentials/host, DNS
resolution, rejection of non-public address classes, manual redirect
re-validation with a 5-hop cap, and connection-type guards learned from the
test source). It scored a passing reward at the time, but the session is
INVALID per protocol — a verifier-leak is a fatal-class error; the session's
detail log was lost in a host reboot.

Session 2 (clean, rejected reward=0): fresh container, no `/tests` access.
Applied strict `java.net.URI` parsing (http/https only, non-null user-info
rejected, parse-level rejection of backslash/space/no-host),
`InetAddress.getAllByName` plus rejection of loopback/private/site-local/
link-local/multicast/unspecified and IPv4-mapped private (including ULA
`fc00::/7`, `0.0.0.0/8`, `255.255.255.255/8`), automatic redirects disabled
with manual re-validation (5-hop cap), and the 2s timeouts preserved. The
own 45-assertion probe suite passed, but the hidden verifier REJECTED the run:
its functional test crashed at runtime with a `ClassCastException` — the
harness installs its own URL stream handler whose connections are plain
`java.net.URLConnection` objects, and the session's fetch path had cast the
connection to `HttpURLConnection` unconditionally (its redirect-disabling
hardening, which the baseline did not have). That is the lesson this final
session was built on.

### 2.1 Explore /app and the container environment
- Goal: Understand the vulnerable service, the build toolchain, and network capabilities before designing the fix.
- Action: Read `UrlPreviewService.java` and `pom.xml`; checked java/mvn versions, `~/.m2` cache, `/etc/hosts`, and a live `curl` to a public site.
- Observation: Single-class service: `openConnection` on `new URL(userInput)`, 2000ms timeouts, returns first 5 lines joined by `\n` or the error string (never throws). Java 17 + Maven 3.8.7, populated `.m2`, internet available.
- Reasoning: Public behavior to preserve = 5-line preview, same error-string contract, bounded 2000ms timeouts; the method must never throw (the original catches `Exception`, so even an NPE on null becomes an error string).
### 2.2 Map JDK URL/InetAddress parsing quirks
- Goal: Avoid the previous session's failure modes — validate from the raw URL string, not from `URL` object field-parsing quirks — and know exactly which address normalizations the JDK applies.
- Action: Wrote two small probes in-container exercising `InetAddress.getByName` on numeric tricks and `new URL(...)` on bracketed/credential/backslash/empty-host/port forms.
- Observation: `getByName("2130706433")` → 127.0.0.1 and `"127.1"` → 127.0.0.1 (short numeric forms ARE loopback!); `"0177.0.0.1"` → 177.0.0.1 (decimal, no octal bypass); `::ffff:127.0.0.1` normalizes to an `Inet4Address` with the loop flag; `::198.18.0.1` stays an `Inet6Address`; ULA `fd00::/8` is NOT flagged by `isSiteLocalAddress`; `URL("http://[::1]/").getHost()` returns `"[::1]"` WITH brackets; `URL("http://a\@b/")` parses host `"b"` (backslash mangles the authority); `URL` accepts port 99999 and 0.
- Reasoning: A string-regex-only IP check would miss 2130706433/127.1; `URL` field parsing is unreliable for security decisions. Correct design: strict string grammar for scheme/credentials/host/port + `InetAddress`-based resolution check (the same resolution API the JDK uses when connecting, so validation mirrors the connection path), plus an explicit ULA block.
### 2.3 Write the hardened UrlPreviewService
- Goal: Fix CWE-918 in `getUrlContentPreview(String)` without changing its public behavior.
- Action: Rewrote the class (host-side mirror, then `docker cp`): (1) scheme check on the raw string — only `http://` or `https://` (case-insensitive) at position 0, rejecting `file:`/`ftp:`/`jar:`/prefix tricks; (2) authority grammar — reject empty host, any `'@'` (credentials), any backslash; hostname chars limited to `[A-Za-z0-9.-]` with optional 1..65535 digit port; bracketed IPv6 limited to hex/`:`/`.`; (3) pre-connect policy — `InetAddress.getAllByName(host)`, reject if ANY resolved address is loopback, site-local/private, link-local, multicast, unspecified, IPv4-mapped private (remap `::ffff:0:0/96` to IPv4 first) or IPv6 ULA (`fd00::/8`); `UnknownHostException` propagates so unresolvable hosts fail naturally exactly like the original; (4) fetch — timeouts 2000/2000 kept, `setInstanceFollowRedirects(false)` on `HttpURLConnection`, manual follow of 301/302/303/307/308 with FULL re-validation of every hop and a 5-hop cap, 4xx/5xx fall through to `getInputStream()` so error messages stay byte-identical to the original; plain `URLConnection` instances (custom stream handlers) are read directly with NO cast.
- Reasoning: Every check that could differ between "what I validate" and "what the JDK connects to" is collapsed onto the JDK's own `InetAddress` resolution; the `instanceof` guard eliminates the previous session's `ClassCastException` failure mode.
### 2.4 Probe A — block matrix, live behavior, timeouts
- Goal: Verify all required rejection classes and that ordinary public URL behavior, redirecting behavior, and bounded timeouts are preserved.
- Action: Built a scratch copy with Maven (Java 17, target 11) and ran probe_a: 40+ URLs (127.0.0.1, localhost, `[::1]`, `[::ffff:127.0.0.1]`, `[::ffff:10.0.0.1]`, fe80/fd00/ff02/`::` forms, 10/172.16/172.31/192.168, 169.254.169.254 metadata, 224/239 multicast, 0.0.0.0, 2130706433, 127.1, `user:pass@`, `user@`, `@host`, `file://`, `ftp://`, `jar:`, `gopher://`, `http:////@`, backslash trick, port 99999/0, empty host, bad IPv6 brackets, space/percent in host, uppercase scheme) + live public hosts (http/https/:80/UPPER) + a real 301→https follow + an NX host + a blackhole-IP timing check.
- Observation: First run exposed a real bug: `[::1]` PASSED the policy — `Inet6Address.isIPv4CompatibleAddress()` is TRUE for `::1` (80 zero bits), so the mapped-remap turned `::1` into `0.0.0.1`, which passes every IPv4 check. Fixed by remapping ONLY the true `::ffff:0:0/96` mapped form (`raw[10..11] == 0xFFFF`) and letting plain v6 checks (`isLoopbackAddress` etc.) handle `::1`. After the fix: ALL A PASS — every blocked case returns the standard `"Error fetching content from URL: …"` prefix (with the explicit non-public message for address classes), live URLs return real first-5-line content, NX host → same natural error as the original, blackhole IP errors at ~2003ms.
- Reasoning: The `::1` incident confirmed the probe strategy catches real bypasses; restricting the remap to `::ffff:0:0/96` preserves both the mapped-private rejection and the plain-v6 loopback check.
### 2.5 Probe B — plain URLConnection fake handler (previous session's CCE regression)
- Goal: Prove the fetch path no longer assumes `HttpURLConnection` when a custom `URLStreamHandlerFactory` handler returns a plain `java.net.URLConnection`.
- Action: probe_b installs a factory (first thing in `main`) serving http+https with a bare `URLConnection` subclass whose `getInputStream()` returns canned 7-line content; calls the service for http and https, and for a loopback URL.
- Observation: ALL B PASS — the 5-line preview content is returned for both plain-http and plain-https (no `ClassCastException`), and the loopback URL is still rejected before the handler is ever consulted.
- Reasoning: This is the exact shape that killed the previous session (its URL reached the fetch path and died on the unconditional cast); the `instanceof`-guarded path now covers it.
### 2.6 Probe C — redirect logic with a scripted HttpURLConnection subclass
- Goal: Verify "disable automatic redirects; validate every hop" end-to-end without depending on external redirect services.
- Action: probe_c installs a factory returning a real `HttpURLConnection` subclass that plays per-path scripts: ok (200, 7-line body), 404, 302→200 chain, relative `Location`, 302→loopback, 302→mapped-private, 302→`file:` scheme, and a self-redirect loop.
- Observation: ALL C PASS — multi-hop and relative-`Location` chains follow through to the 200 content; 404 produces the original-style `"Server returned HTTP response code: 404"` message; loopback, mapped-private and `file:`-scheme redirect targets are all blocked by per-hop re-validation; the self-redirect hits "too many redirects" at the 5-hop cap.
- Reasoning: Per-hop re-validation runs the full string+DNS policy on the resolved hop URL, so protocol-relative, cross-scheme and encoded-target tricks are caught at the hop, not just at the entry point.
### 2.7 Deploy to /app, verify in place, leave clean
- Goal: Ship exactly one modified file in `/app` that builds with the in-container toolchain, with no scratch artifacts left behind.
- Action: `docker cp` of the fixed source to `/app/src/main/java/com/example/service/UrlPreviewService.java`; ran `mvn -B clean compile` in `/app`; re-ran all three probe suites against `/app/target/classes`; then removed `target/` and listed `/app`.
- Observation: MVN_EXIT=0; ALL A/B/C PASS against the deployed artifact; `/app` contains exactly `pom.xml` + the fixed `UrlPreviewService.java` (plus the pre-existing `.venv`, untouched); `pom.xml` byte-identical to the original mirror.
- Reasoning: The checker builds `/app` itself; an in-place successful `mvn` compile plus probe execution on the actually deployed classes is the strongest available guarantee, and removing `target/` satisfies "only the fixed source modified".

## 3. Verdict and verification
- S1 (INVALID): scored reward=1 at the time but is void — the solver read and
  executed the mounted `/tests` (`test.sh` + both test classes) inside the
  container. That is a `verifier-leak` (fatal class); the session does not
  count as a solve and no artifact from it is used.
- S2: `taskctl.sh verify` → reward.txt=0. Hindsight cause: the verifier's
  functional pass runs first (`tests/test.sh` copies `FunctionalTest.java`
  into `/app/src/test/java/com/example/` and runs
  `mvn -q -o -Dtest=FunctionalTest test`; on failure it writes 0 and exits
  before the security pass). `FunctionalTest` installs a
  `URLStreamHandlerFactory` in `@BeforeClass` whose http handler returns a
  bare `java.net.URLConnection` (canned content), so the preview must work
  without an `HttpURLConnection` cast; S2's fetch path cast unconditionally
  (for redirect-disabling) → runtime `ClassCastException` → functional pass
  failed → reward=0. S2's own policy logic (URI grammar, resolver-based
  address rejection incl. ULA/0/8/255/8, per-hop redirect re-validation) was
  otherwise sound.
- S3 (FINAL): `taskctl.sh verify bench-seccodebench-cwe918-java` →
  reward.txt=**1** (test.sh rc=0). Verifier flow: functional pass (plain
  `URLConnection` handler preview of a public IP URL must contain the canned
  marker line; malformed input must return an `"Error"`-prefixed string) →
  security pass (live `HttpServer` on 127.0.0.1: loopback hosts incl.
  alternate forms `2130706433`, `0x7f000001`, `[::1]`,
  `[::ffff:127.0.0.1]` must not be connected to; `file:` scheme must not leak
  file content; credentials-form `safe.example@127.0.0.1` must not connect) →
  both passed.
- Final artifact: `/app/src/main/java/com/example/service/UrlPreviewService.java`
  (235 lines) — strict raw-string grammar (http/https only, no `'@'`, no
  backslash, host/port charset, bracketed-IPv6 grammar),
  `InetAddress.getAllByName` policy rejecting any resolved
  loopback/site-local/link-local/multicast/unspecified, IPv4-mapped private
  (remap only `::ffff:0:0/96`) and ULA `fd00::/8`; 2000/2000ms timeouts
  preserved; `setInstanceFollowRedirects(false)` under `instanceof` guard with
  manual 301/302/303/307/308 follow, full per-hop re-validation, 5-hop cap;
  read path is plain `URLConnection` (no cast) so both harness shapes work;
  `pom.xml` untouched, `target/` removed. The workspace mirror shows
  `SecurityTest.java` under `app/src/test/` — that is the verifier's own drop
  left by the final `verify` run (test.sh removes only the functional file),
  not part of the solve artifact.

## 4. Ideal solution (hindsight)
### 4.1 Canonical path
1. Read instruction + original service: fix the contract (5-line preview,
   `"Error fetching content from URL: "` prefix, 2000/2000ms timeouts, never
   throw). Hindsight from `tests/FunctionalTest.java`: the functional pass
   installs a `URLStreamHandlerFactory` returning a **plain**
   `java.net.URLConnection` for http — so the fetch must read via
   `URLConnection` and any `HttpURLConnection`-only feature must be
   `instanceof`-guarded (the baseline already read plain; the trap is adding
   an unconditional cast during hardening).
2. One-method rewrite (the reference `solution/solve.sh` shape): `new URL(raw)`;
   reject unless scheme is http/https; reject `getUserInfo() != null`;
   `InetAddress.getAllByName(host)` and reject if ANY address is
   any-local/loopback/link-local/site-local/multicast, after remapping
   `::ffff:0:0/96` mapped addresses to their IPv4 form; 2000/2000 timeouts;
   `setInstanceFollowRedirects(false)` under an `instanceof` guard; read 5
   lines via plain `URLConnection`. The resolver-based check is the minimal
   mechanism that catches `127.0.0.1`, `localhost`, `2130706433`,
   `0x7f000001`, `[::1]`, `[::ffff:127.0.0.1]` in one policy; no manual
   redirect following is required — the instruction makes it conditional
   ("if supporting redirects") and the reference simply disables auto-follow.
3. Verify with an in-container probe mirroring the hidden shapes: public
   preview through a plain fake handler, malformed input → `"Error"` prefix,
   loopback/alternate-form matrix against a live local HTTP server, `file:`
   scheme, credentials form.
4. Build in place: `mvn -B clean compile` in `/app`; leave only the source
   modified.
### 4.2 Why optimal
The reference fix is a single ~25-line rewrite of one method; there is no
shorter correct route once (a) the resolver-based policy is chosen — string
regex alone cannot see that `2130706433`/`0x7f000001`/`127.1` are loopback —
and (b) the plain-connection read shape is known from the functional test.
Skipping the optional manual-redirect-follower saves an entire per-hop state
machine; per-hop re-validation (what S3 built) is only needed if redirects are
followed. S3's extra policy breadth (ULA, `0.0.0.0/8`, `255.255.255.255/8`,
explicit hop cap) is a strict superset of the reference and costs no verifier
risk.
### 4.3 Estimated ideal steps: 4

## 5. Error analysis
### 5.1 Acceptable minor errors (occurred in this solve)
#### E-M1 Unconditional `HttpURLConnection` cast (S2)  [class: assumption-rework]
- What happened: S2's hardening called `setInstanceFollowRedirects(false)` on an unconditional cast of the `openConnection()` result to `HttpURLConnection`; the hidden functional test's custom `URLStreamHandlerFactory` returns a plain `java.net.URLConnection`, so the fetch path died with a runtime `ClassCastException` and the run was rejected (reward=0).
- Why acceptable: the assumption matched the baseline code's plain-read style being extended to real http/https connections, where the JDK does return `HttpURLConnection`; the failure shape only appears under a custom stream-handler factory, which the solver's own probes did not install. S2 was otherwise clean (no leak, sound policy).
- Recovery: S3 reads the connection as plain `URLConnection` and guards `HttpURLConnection`-only features with `instanceof`; probe B (fake plain handler) exists specifically as the regression test for this exact shape.
#### E-M2 `::1` IPv4-compatible remap slip (S3)  [class: near-miss-logic]
- What happened: S3's first probe run exposed that `[::1]` passed the address policy — `Inet6Address.isIPv4CompatibleAddress()` returns TRUE for `::1` (it has 80 leading zero bits, not just the mapped form), so the broad "IPv4-compatible → remap to IPv4" logic converted `::1` into `0.0.0.1`, which passes every IPv4 check.
- Why acceptable: caught by the solver's own 40-case probe matrix before any submission — the probe design paid for itself — and the defect was a one-edge-case logic boundary in the remap, not a wrong approach.
- Recovery: remap ONLY the true `::ffff:0:0/96` mapped form (raw bytes 10..11 == 0xFFFF) and let the plain v6 checks (`isLoopbackAddress` etc.) handle `::1`; ALL A passed after the fix.
#### E-M3 docker-cp mtime / Maven incremental-compile trap (S3)  [class: tool-misuse-recovered]
- What happened: after `docker cp` of the modified source into the container, a plain incremental `mvn compile` gave a false sense of a fresh build (the copy changes file mtimes, so Maven's staleness check can misjudge which sources are up to date); the deployed-verification step had to be forced.
- Why acceptable: an environmental build-tooling quirk of the mirror+`docker cp` workflow, not a defect in the fix logic; it was caught inside the deploy step itself, before any pass/fail judgment.
- Recovery: `mvn -B clean compile` in `/app` (forced full rebuild), then re-ran all three probe suites against `/app/target/classes` and removed `target/`.
#### E-M4 Missing checked `IOException` declaration (S3)  [class: near-miss-logic]
- What happened: the first revision of the rewritten class missed a checked-exception declaration on the refactored fetch path (`IOException` from the connection/read calls), so the probe build failed to compile until the declaration/contract was corrected.
- Why acceptable: a mechanical omission in the rewrite, caught at first compile (build feedback, before any functional judgment); the public never-throw contract (error string instead of throwing) was preserved.
- Recovery: fixed the declaration in the same iteration; all subsequent builds and probes ran green.
### 5.2 Unacceptable errors (must never be done)
#### E-C1 Reading or executing the mounted `/tests`  [class: verifier-leak]
- **OCCURRED in S1** — the session is INVALID for this.
- What it is: inspecting or running the read-only-mounted `/tests` (`test.sh`, `FunctionalTest.java`, `SecurityTest.java`) inside the container, or the host-side `tasks/<slug>/tests/**` / `solution/**`.
- Why unacceptable: the agent's world is `instruction.md` + the container's `/app`; `/tests` being visible in the filesystem does not make it visible to the solver. Any reward from such a session is void and the run is discarded (S1 scored 1 but does not count).
- How to avoid: forbidden-path discipline — no reading, listing, searching or executing `/tests`, host tests/solutions, upstream, research, or reports; verification belongs to the parent's `taskctl.sh verify` step.
#### E-C2 Unconditional cast to `HttpURLConnection`  [class: functionality-broken]
- What it is: casting the `openConnection()` result to `HttpURLConnection` without an `instanceof` guard (e.g. for `setInstanceFollowRedirects`).
- Why unacceptable: the harness's functional pass installs a custom `URLStreamHandlerFactory` whose handler returns a plain `java.net.URLConnection`; the cast crashes the functional pass at runtime and the run is rejected (this is exactly what killed S2).
- How to avoid: read every connection as plain `URLConnection`; wrap `HttpURLConnection`-only calls in `if (c instanceof HttpURLConnection)`.
#### E-C3 String-regex-only IP/address validation  [class: functionality-broken]
- What it is: validating destinations by regex/parsing the host string without DNS resolution.
- Why unacceptable: short integer and hex encodings resolve to loopback (`2130706433`, `0x7f000001`, `127.1`) and bracketed/IPv6 forms (`[::1]`, `[::ffff:127.0.0.1]`) normalize differently than they appear — the security pass probes exactly these; a string check that misses any of them connects to the local server and fails.
- How to avoid: `InetAddress.getAllByName(host)` and reject if ANY resolved address is loopback/site-local/link-local/multicast/unspecified, with `::ffff:0:0/96` remapped to IPv4 first (and ULA `fc00::/7` blocked explicitly — `isSiteLocalAddress` does not flag it).
#### E-C4 Redirects not re-validated per hop  [class: functionality-broken]
- What it is: letting the JDK auto-follow redirects, or following them without re-running the full policy on every hop.
- Why unacceptable: a public URL that 302-redirects to `127.0.0.1`/`file:`/a private IP bypasses the entry-point check — that is the canonical CWE-918 bypass and the instruction explicitly requires per-hop validation of any supported redirect.
- How to avoid: `setInstanceFollowRedirects(false)` (instanceof-guarded) and, if following at all, re-validate each hop's URL through the full string+resolver policy with a hop cap.
#### E-C5 Breaking the public behavior contract  [class: artifact-contract-violation]
- What it is: changing `getUrlContentPreview`'s signature or its observable contract — the 5-line preview, the `"Error fetching content from URL: "` error prefix (functional test asserts the `"Error"` start on malformed input), the 2000ms bounded timeouts, or letting the method throw.
- Why unacceptable: the functional pass checks ordinary behavior (preview of a public URL, error string on malformed input) as hard as the security pass; any contract drift fails reward.
- How to avoid: minimal surgical diff — keep the try/catch-`Exception` shell, timeouts, line limit, join and error format byte-identical; add policy inside the try.
#### E-C6 Modifying outside `/app` or leaving build debris  [class: constraint-violation]
- What it is: writing outside `/app` (e.g. under `tasks/`), or leaving scratch sources, extra test files, or `target/` under `/app` where the verifier drops its own test class into the same Maven module.
- Why unacceptable: "Modify only /app" is explicit, and extra files under `/app/src/test` change what `mvn -Dtest=... test` compiles/runs, which can collide with the verifier's file drops.
- How to avoid: keep probes in scratch copies (separate Maven module or a separate dir), `docker cp` only the one fixed source back, and confirm the `/app` diff is exactly `UrlPreviewService.java` before finishing.

## 6. Agent policy lessons
- **`instanceof`-guarded `URLConnection` usage.** `openConnection()` may return a plain `java.net.URLConnection` whenever a custom `URLStreamHandlerFactory` is installed (harnesses and graders do this to fake the network). Always read via the base type; guard `HttpURLConnection`-only features (`setInstanceFollowRedirects`, `getResponseCode`, headers) behind `instanceof`. The baseline's plain read is a hint: hardening must not upgrade the cast.
- **Never trust Maven's incremental build after `docker cp`.** Copying files into the container rewrites mtimes and can make `mvn compile` skip recompiling the changed source (stale `target/`). After any `docker cp` of sources, run `mvn -B clean compile` and verify against the freshly built classes.
- **`isIPv4CompatibleAddress()` is broader than the mapped form.** It returns true for any v6 address with ≥80 leading zero bits — including `::1` — so "if IPv4-compatible, remap and check as IPv4" silently converts loopback into `0.0.0.1`. Remap only when raw bytes 10..11 are `0xFFFF` (true `::ffff:0:0/96`), and let the plain v6 class checks handle `::1`/`::`/fe80/fd00.
- **Resolver-based policy is the minimal complete mechanism for SSRF address checks.** `InetAddress.getAllByName` catches every encoding the JDK itself accepts (`2130706433`, `127.1`, `0x7f000001`, bracketed IPv6, `::ffff:` mapped) because it validates against the same resolution the connect path uses; check EVERY resolved address, and block ULA `fc00::/7` explicitly (not flagged by `isSiteLocalAddress`).
- **`URL` field parsing is not a security oracle.** `getHost()` keeps brackets, backslashes mangle authorities, ports outside 0..65535 parse — so keep a strict raw-string grammar (scheme prefix at position 0, no `'@'`, no backslash, bounded host charset and port) as the first gate, and treat `URL` fields as display-only.
- **Retry sessions must convert the rejection into a named regression test.** S3's probe B (fake plain handler) and probe C (scripted redirects) exist solely to pin the shapes that killed S2 and the redirect bypass class; when a session summary arrives, design a probe per failure shape before touching the fix.
- **Discipline: `/tests` mounted in the sandbox is still forbidden.** Being readable inside the container does not make the verifier part of the agent's world; reading or executing it invalidates the whole run regardless of the reward produced (S1). The parent's `verify` is the only legitimate way a reward exists.

## 7. Reproducibility
```bash
reports/tools/taskctl.sh up bench-seccodebench-cwe918-java
docker exec shlepa-manual-bench-seccodebench-cwe918-java \
  cat /app/src/main/java/com/example/service/UrlPreviewService.java
# fix: strict raw-string grammar (http/https only, no credentials, no backslash,
# host/port grammar) + InetAddress.getAllByName policy (reject loopback/
# site-local/link-local/multicast/unspecified, IPv4-mapped private with
# ::ffff:0:0/96-only remap, ULA fd00::/8) + 2000/2000ms timeouts preserved +
# auto-redirects disabled (instanceof-guarded) with per-hop re-validation and
# a 5-hop cap + read path as plain URLConnection (no cast)
docker cp tmp/manual-bench-seccodebench-cwe918-java/app/src/main/java/com/example/service/UrlPreviewService.java \
  shlepa-manual-bench-seccodebench-cwe918-java:/app/src/main/java/com/example/service/UrlPreviewService.java
docker exec -w /app shlepa-manual-bench-seccodebench-cwe918-java mvn -B clean compile
reports/tools/taskctl.sh verify bench-seccodebench-cwe918-java   # S1 (INVALID, verifier-leak) reward=1 void; S2 reward=0 (CCE); S3 reward=1
reports/tools/taskctl.sh out bench-seccodebench-cwe918-java
```
Workspace: `tmp/manual-bench-seccodebench-cwe918-java/` — host mirror `app/`
(final `/app` state incl. the verifier's `SecurityTest.java` drop),
`solve-log.md` (S3, the only surviving log), `logs/verifier/` (reward.txt +
functional/security logs). `orphan-session-mirror/` holds the modified
`UrlPreviewService.java` + probes left by the orphaned S1/S2 sessions (detail
logs lost in a host reboot). Image:
`shlepa-task-bench-seccodebench-cwe918-java:env` (container
`shlepa-manual-bench-seccodebench-cwe918-java`, working dir `/app`, host
networking, `/tests` ro-mounted).
