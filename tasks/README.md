# Vendored contest tasks

Local dev runs of vendored contest tasks via `shlepa run`.

## Registry

| slug | source | synced | difficulty | description |
|------|--------|--------|------------|-------------|
| contest-hello-file | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | easy | Create hello.txt with exact content. |
| contest-bye-file | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | easy | Create bye.txt with exact content. |
| contest-find-sqli-login | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | easy | Analyze a FastAPI application and report security vulnerabilities in machine-readable JSON. |
| contest-fix-sqli-login | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | medium | Find and fix a SQL injection vulnerability in a FastAPI application. |
| contest-fix-sqli-search | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | medium | Find and fix a SQL injection vulnerability in a FastAPI application. |
| contest-incident-log-forensics | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | medium | Correlate proxy, application, and auth logs to attribute an exfiltration incident. |
| contest-insecure-api-app | SecureIntelligent/UniversalAgenticCompetitionPublic | 2026-08-26 | n/a | FastAPI app source with variant patches (no `task.toml` upstream — not discoverable/runnable). |
| bench-seccodebench-cwe89 | alibaba/sec-code-bench (v2.2.0) | 2026-08-27 | medium | Fix the SQL injection (CWE-89) in the user_activity_logger module (psycopg2, mocked DB). |
| bench-seccodebench-cwe78 | alibaba/sec-code-bench (v2.2.0) | 2026-08-27 | medium | Fix the OS command injection (CWE-78) in the ssh_login_history module (subprocess, shell=True). |
| bench-seccodebench-cwe1336 | alibaba/sec-code-bench (v2.2.0) | 2026-08-27 | medium | Fix the server-side template injection (CWE-1336) in the profile_renderer module (Jinja2). |

Descriptions are taken from the `[task] description` field of each upstream `task.toml`.

## Syncing upstream changes

1. Shallow-clone the upstream repo into a throwaway dir outside the repo:
   `git clone --depth 1 https://github.com/SecureIntelligent/UniversalAgenticCompetitionPublic /tmp/ua-vendor-<timestamp>`
2. For each task, copy the upstream dir over the vendored one (byte-identical):
   `cp -r /tmp/ua-vendor-<timestamp>/local_task/<upstream-dir> tasks/contest-<slug>/`
3. Re-apply the `[metadata]` provenance keys in each copied `task.toml` (keep all upstream keys intact; append after the `tags` line):
   - `source = "SecureIntelligent/UniversalAgenticCompetitionPublic"`
   - `url = "https://github.com/SecureIntelligent/UniversalAgenticCompetitionPublic/tree/main/local_task/<upstream-dir>"`
   - `synced_at = "<sync date, YYYY-MM-DD>"`
4. Diff-verify byte-identity — the only expected difference is the `[metadata]` provenance keys in `task.toml`:
   `diff -r /tmp/ua-vendor-<timestamp>/local_task/<upstream-dir> tasks/contest-<slug>`
5. Update `synced_at` in each touched `task.toml`.
6. Commit: `git add tasks && git commit -m "chore(tasks): sync contest tasks from upstream"`
7. Clean up the throwaway clone: `rm -rf /tmp/ua-vendor-<timestamp>`

## Notes

- Upstream lives in `local_task/`; every canonical slug matched the upstream dir name exactly (no mapping differences as of 2026-08-26).
- `contest-insecure-api-app` is vendored as source material only: upstream has no `task.toml`, `instruction.md`, or `tests/` for it, so `discover_tasks` ignores it and it cannot be run with `shlepa run`. It holds the `app/` sources, `sync.sh`, and `variants/` used to generate the fix-sqli-* tasks.

See [docs/tasks.md](../docs/tasks.md) for task format details.
