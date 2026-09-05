# SOC ticket IR-4821 — suspected ransomware staging

An alert cluster fired on `WS-ACCT-05` between 02:14 and 02:20 UTC. Review all JSONL artifacts under `/app/evidence/`, decide whether this is an incident, and write `/app/report.json`.

The report must contain exactly these keys:

```json
{"verdict":"TRUE_POSITIVE_INCIDENT|FALSE_POSITIVE_AUTHORIZED_PENTEST|BENIGN_ANOMALY","primary_mitre_technique":"Txxxx[.xxx]","compromised_hosts":["host"],"compromised_accounts":["account"],"key_indicators":["verbatim evidence value"]}
```

Use the single most important ATT&CK technique. Include at least two indicator strings copied verbatim from JSON values in the evidence. Do not invent entities or use prose outside the JSON file.
