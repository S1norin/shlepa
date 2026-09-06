# Audit the synthetic export CLI

You are working in `/app`. Review the Java source under `/app/src/`. This
offline CLI sketch contains one deliberately planted security logic defect.

Do not modify the source. Write `/app/security_report.json` as a JSON object
with a non-empty `findings` array. Each finding must contain `title`,
`severity`, `category`, `location`, `evidence`, `impact`, and `recommendation`.
Name the CWE, describe a concrete malicious filename, identify the affected
filesystem operation, and explain a repair that also addresses symbolic links.
