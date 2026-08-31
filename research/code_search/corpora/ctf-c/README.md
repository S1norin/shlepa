# ctftest C corpus (own)

Synthetic C source corpus for search-engine measurement
(`research/code_search/analysis/`). It is NOT a real CTF challenge:
the vendored CTFTiny tasks are binary-only, so this small pwn-style
project stands in for the "CTF code" family in the search benchmarks.

Structure mirrors a typical binary-exploitation target: a CLI auth
daemon with a stack-buffer processing path, a planted flag-reveal
function, an embedded translation table, and weak credential checks.

Provenance: authored in this repo, 2026-08-31 (code-search-tools plan,
measure-harness). 15 files, no build required for measurement.
