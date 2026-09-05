# Fix CWE-79 in the Go feedback-email builder

The implementation in `/app/main.go` interpolates untrusted values into an HTML email and its headers. Fix `BuildFeedbackEmail` while preserving its signature and valid Unicode content.

Requirements: return an RFC-style HTML email; reject CR/LF header injection in address or subject inputs; escape every user-controlled value placed in HTML; keep valid sender/recipient validation. Run tests with `go test ./...`. Modify only files under `/app`.
