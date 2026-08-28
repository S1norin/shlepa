# SOC ticket AL-3318 — process anomaly on domain controller DC01

The `dc-process-anomaly` rule fired on **DC01.corp.local** around
**09:00–09:10 UTC on 2026-04-15**. You are the analyst on duty. Review
the artifacts under **`/app/evidence/`**, determine whether this is a
real incident, and record your structured verdict in
**`/app/report.json`**.

**Artifacts:**

- `ticket_context.txt` — the alert context.
- `windows_event_logs.jsonl` — Windows Event Log export for the window
  (process, logon, and object-access events from multiple hosts).
- `background_activity.jsonl` — routine background activity feed for the
  same window (for context; not every entry is security-relevant).

**Deliverable — strict machine format**

Write **`/app/report.json`**: a single JSON object with **exactly** these
keys (no extra keys, no comments):

```json
{
  "verdict": "<one of the three values below>",
  "primary_mitre_technique": "<MITRE ATT&CK technique ID, e.g. T1003.003>",
  "compromised_hosts": ["<host name>"],
  "compromised_accounts": ["<user account>"],
  "key_indicators": ["<string taken verbatim from the evidence>"]
}
```

- `verdict` must be one of:
  - `TRUE_POSITIVE_INCIDENT` — unauthorized malicious activity
  - `FALSE_POSITIVE_AUTHORIZED_PENTEST` — activity matches an approved
    security engagement (authorized pentest / scan)
  - `BENIGN_ANOMALY` — unusual but benign, and not an authorized
    engagement
- `primary_mitre_technique` — the single most important MITRE ATT&CK
  technique ID for the observed behaviour (empty string if the verdict is
  not `TRUE_POSITIVE_INCIDENT`).
- `compromised_hosts` — hosts on which the malicious activity was
  executed (empty list if the verdict is not `TRUE_POSITIVE_INCIDENT`).
- `compromised_accounts` — accounts used to execute the malicious
  activity (empty list if the verdict is not `TRUE_POSITIVE_INCIDENT`).
- `key_indicators` — at least two indicator strings copied from the
  evidence that support the verdict: the executed command and the file
  object it was used against. Each string must appear verbatim in one of
  the evidence files.

Cite only evidence present in the artifacts; do not invent hosts,
accounts, or indicators.
