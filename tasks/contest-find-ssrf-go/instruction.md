# Audit the synthetic link-card service

You are working in `/app`. Review the Go source under `/app/src/`. The service
is deliberately small and contains one planted security logic defect.

Do not modify the application. Write `/app/security_report.json` as a JSON
object containing a non-empty `findings` array. Each finding must contain
`title`, `severity`, `category`, `location`, `evidence`, `impact`, and
`recommendation` strings. Identify the applicable CWE, affected handler and
sink, a concrete bypass of the existing validation, the impact, and a repair
that covers redirects and resolved IP addresses.
