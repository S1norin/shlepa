RECON SCRIPT
- A bundled zero-dependency recon script is available at tools/recon.py
(fallback in dev mode: /agent/tools/recon.py). For a live local target
(a running web service or API), run `python3 tools/recon.py <url>` first
instead of many exploratory curl requests: it prints a compact JSON
attack-surface summary (ports, service fingerprints, discovered endpoints)
in well under a minute.
- For code tasks run `python3 tools/recon.py --code <path>` to map sinks,
inputs, and entry points; for data/artifact tasks run
`python3 tools/recon.py --data <path>` to find flags, secrets, and encoded
strings. Output is deterministic JSON, capped at 8 KB.
