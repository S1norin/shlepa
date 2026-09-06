# Audit the synthetic billing API

You are working in `/app`. Review the small Node.js application under
`/app/src/`. It contains one deliberately planted security logic defect.

Do not modify the source. Write `/app/security_report.json` as a valid JSON
object containing a non-empty `findings` array. Each finding must contain
`title`, `severity`, `category`, `location`, `evidence`, `impact`, and
`recommendation` strings. Name the CWE, identify the affected endpoint and
missing decision, explain a concrete cross-account impact, and propose where
and how authorization must be enforced.
