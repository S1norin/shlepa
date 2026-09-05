# SOC ticket CLD-1179 — anomalous Microsoft 365 activity

Several identity, mail, and network alerts fired for the CFO account on 2026-04-10. Review all JSONL artifacts under `/app/evidence/`, determine whether this is an incident, and write `/app/report.json`.

The report must contain exactly these keys:

```json
{"verdict":"TRUE_POSITIVE_INCIDENT|FALSE_POSITIVE_AUTHORIZED_PENTEST|BENIGN_ANOMALY","primary_mitre_technique":"Txxxx[.xxx]","compromised_hosts":["host"],"compromised_accounts":["account"],"key_indicators":["verbatim evidence value"]}
```

Use the single most important ATT&CK technique. Cloud-only activity may have no compromised host. Include at least two indicator strings copied verbatim from JSON values in the evidence. Do not invent entities or use prose outside the JSON file.
