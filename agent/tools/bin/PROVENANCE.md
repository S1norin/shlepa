# Vendored binary provenance

## sifs

- **Version:** 0.4.0
- **Source:** <https://github.com/tristanmanchester/sifs> · crate [`sifs` 0.4.0](https://crates.io/crates/sifs) (2026-05-28)
- **License:** MIT
- **Target:** x86_64-unknown-linux-gnu, dynamically linked (glibc). Verified to run on Debian 12 inside `secureintelligent/acp:latest` (`sifs --version` via `docker run`).
- **Build date:** 2026-08-30
- **Toolchain:** rustc 1.95.0 (59807616e 2026-04-14) · cargo 1.95.0 (f2d3ce0bd 2026-03-21)
- **Build profile:** release with `lto=true`, `codegen-units=1`, `panic=abort`, `strip=symbols`, plus the reproducibility settings below (all pinned in `rebuild-sifs.sh`)
- **sha256:** a850ff780c9b0ddc46507e4cc477da7ab2c64f9fbdb4a801ba3c05bf450d2709
- **Raw size:** 9711816 bytes (9.3 MB) · ~3.87 MB deflate-9 in the submission zip (zip gate: total <= 10 MB)
- **Use:** BM25-offline code search only in the submission path (`sifs search|symbol|outline|find-related --mode bm25 --offline --json`). Semantic/hybrid modes need a 61.4 MB embedding model and are dev-only (see `research/code_search/notes/sifs.md`).

### Reproducibility

A plain `cargo install` is **not** byte-reproducible: (1) the linker's
`.note.gnu.build-id` (SHA1 over the output) varies, and (2)
`tree-sitter-language-pack`'s build script embeds its `OUT_DIR` absolute
path, which under `cargo install` contains a random temp-dir name
(`/tmp/cargo-installXXXXXX/...`). Both are suppressed here:

- `RUSTFLAGS="-C link-args=-Wl,--build-id=none"` — no build-id note;
- `CARGO_TARGET_DIR=/tmp/sifs-target` — fixed, non-random build path, so the
  embedded `OUT_DIR` string is constant.

With these settings the build was verified byte-identical (same sha256)
across repeated builds on the recorded toolchain.

### Rebuild

```sh
# Reproduce the pinned binary (requires cargo + network to crates.io):
sh agent/tools/bin/rebuild-sifs.sh
# Verify the committed sha256 without touching the binary:
sh agent/tools/bin/rebuild-sifs.sh --check
# After a deliberate rebuild (new toolchain or sifs patch release):
# 1. re-verify in the ACP container (docker run ... /sifs --version, glibc),
# 2. then re-pin the recorded values:
sh agent/tools/bin/rebuild-sifs.sh --update-provenance
```

A sha256 mismatch means the build environment differs from the recorded one;
do not install the binary until it re-passes the container check.
