# SOC ticket AWS-2904 — sensitive bucket policy change

Cloud posture monitoring detected a policy change on a production S3 bucket. The source IP `10.10.5.162` is assigned to `WS-HR-14`. Review all JSONL artifacts under `/app/evidence/`, distinguish the suspicious event from background activity, and write `/app/report.json`.

The report must contain exactly these keys:

```json
{"verdict":"TRUE_POSITIVE_INCIDENT|FALSE_POSITIVE_AUTHORIZED_PENTEST|BENIGN_ANOMALY","primary_mitre_technique":"Txxxx[.xxx]","compromised_hosts":["host"],"compromised_accounts":["account"],"key_indicators":["verbatim evidence value"]}
```

Use the single most important ATT&CK technique. Include at least two indicator strings copied verbatim from JSON values in the evidence. Do not invent entities or use prose outside the JSON file.
