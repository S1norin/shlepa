# SOC ticket AL-3046 — high-entropy DNS TXT volume (2026-04-25)

The `dns-entropy-volume` rule fired repeatedly between 09:00 and 13:00 UTC on 2026-04-25. The exported telemetry for the surrounding window (07:00-13:00 UTC) is attached. You are the analyst on duty.
Review the artifacts under **`/app/evidence/`**, determine whether this
is a real incident, and record your structured verdict in
**`/app/report.json`**.

**Artifacts:**

- `ticket_context.txt` — The alert context.
- `zeek_dns.jsonl` — Zeek DNS log for the window (one JSON object per line).
- `background_activity.jsonl` — Routine background activity feed for the same window (for context; not every entry is security-relevant).

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
  evidence that support the verdict (executed commands, file paths, IP
  addresses, domains, or event identifiers). Each string must appear
  verbatim in one of the evidence files.

Cite only evidence present in the artifacts; do not invent hosts,
accounts, or indicators.
