# SOC ticket AL-4471 — burst of short-lived TCP connections (2026-04-20)

The intrusion-detection rule `tcp-syn-burst` fired after a burst of
one-way TCP connections on **2026-04-20**. You are the analyst on duty.
Review the artifacts under **`/app/evidence/`**, decide whether this is a
real incident, and record your structured verdict in
**`/app/report.json`**.

**Artifacts:**

- `zeek_conn.jsonl` — Zeek connection log for the flagged window (one JSON
  object per line).
- `ticket_context.txt` — the alert context and the matching change
  management record.

**Deliverable — strict machine format**

Write **`/app/report.json`**: a single JSON object with **exactly** these
keys (no extra keys, no comments):

```json
{
  "verdict": "<one of the three values below>",
  "flagged_source_ip": "<the source IP responsible for the flagged activity>",
  "within_approved_window": true
}
```

- `verdict` must be one of:
  - `TRUE_POSITIVE_INCIDENT` — unauthorized malicious activity
  - `FALSE_POSITIVE_AUTHORIZED_PENTEST` — activity matches an approved
    security engagement (authorized pentest / scan)
  - `BENIGN_ANOMALY` — unusual but benign, and not an authorized
    engagement
- `flagged_source_ip` — the single source IP that generated the flagged
  connections.
- `within_approved_window` — JSON boolean: `true` only if the activity
  came from an in-scope source **and** falls inside the approved window
  stated in `ticket_context.txt`.

Cite only evidence present in the artifacts; do not invent IPs, times, or
engagements.
