# Audit the synthetic note-preview service

You are working in `/app`. Review the small Python web application under
`/app/src/` and identify its deliberately planted security logic defect.

Do not modify the application. Write a valid JSON report to
`/app/security_report.json` with this shape:

```json
{"findings":[{"title":"...","severity":"critical|high|medium|low|informational","category":"...","location":"...","evidence":"...","impact":"...","recommendation":"..."}]}
```

The report must name the applicable CWE, identify the affected route and source
line or expression, explain how attacker-controlled input reaches the dangerous
output, and recommend a concrete repair.
