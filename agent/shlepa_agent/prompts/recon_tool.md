RECON TOOL
- Use the recon tool FIRST on attack-surface recon, before curl/grep/read
round trips: it returns a compact deterministic JSON summary (capped at
8 KB) — no LLM, no writes, hard 25 s cap (a url crawl may be cut short —
fall back to targeted reads/search for what it missed).
- mode "url" + target = the URL of a live local web service or API: open
ports, service fingerprints, discovered endpoints, sensitive files.
- mode "code" + target = a source-code directory: entry points, risky
sinks (eval/exec/injection/paths), compose services and ports.
- mode "data" + target = an evidence/log directory: file inventory,
formats, time ranges, flags, secrets and encoded strings.
