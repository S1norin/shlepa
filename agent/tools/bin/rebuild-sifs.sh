#!/bin/sh
# Rebuild the pinned SIFS binary (this directory) and verify its sha256
# against PROVENANCE.md.
#
# Usage:
#   sh rebuild-sifs.sh                  rebuild + verify + install over ./sifs
#   sh rebuild-sifs.sh --check          rebuild in a temp dir, compare only
#   sh rebuild-sifs.sh --update-provenance
#                 rebuild, install, and re-pin sha256/size/date in PROVENANCE.md
#
# Requires: cargo (Rust toolchain) and network access to crates.io.
# The pinned profile + reproducibility settings below reproduce the committed
# binary byte-for-byte on the recorded toolchain (see PROVENANCE.md, section
# "Reproducibility" for why the build-id and the fixed CARGO_TARGET_DIR are
# required). On a different toolchain the sha256 check fails; re-verify the
# binary in the ACP container (glibc) before re-pinning.

set -eu

HERE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BIN="$HERE/sifs"
PROV="$HERE/PROVENANCE.md"
CRATE="sifs@0.4.0"

mode="install"
case "${1:-}" in
  "") mode="install" ;;
  --check) mode="check" ;;
  --update-provenance) mode="update" ;;
  *) echo "usage: $0 [--check | --update-provenance]" >&2; exit 2 ;;
esac

command -v cargo >/dev/null 2>&1 || {
  echo "error: cargo not found (Rust toolchain required)" >&2
  exit 2
}

recorded_sha="$(sed -n 's/^- \*\*sha256:\*\* //p' "$PROV" | tr -d '[:space:]' | head -n 1)"
if [ -z "$recorded_sha" ]; then
  echo "error: no sha256 recorded in $PROV" >&2
  exit 2
fi
recorded_size="$(sed -n 's/^- \*\*Raw size:\*\* \([0-9][0-9]*\) bytes.*/\1/p' "$PROV" | head -n 1)"
[ -n "$recorded_size" ] || { echo "error: no raw size recorded in $PROV" >&2; exit 2; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "building $CRATE (lto, codegen-units=1, panic=abort, strip=symbols, build-id=none)..."
env CARGO_TARGET_DIR=/tmp/sifs-target \
    CARGO_PROFILE_RELEASE_LTO=true \
    CARGO_PROFILE_RELEASE_CODEGEN_UNITS=1 \
    CARGO_PROFILE_RELEASE_PANIC=abort \
    CARGO_PROFILE_RELEASE_STRIP=symbols \
    RUSTFLAGS="-C link-args=-Wl,--build-id=none" \
  cargo install --root "$tmp" --locked "$CRATE"

built="$tmp/bin/sifs"
[ -f "$built" ] || { echo "error: build did not produce bin/sifs" >&2; exit 1; }

new_sha="$(sha256sum "$built" | cut -d' ' -f1)"
new_size="$(wc -c < "$built" | tr -d '[:space:]')"

echo "built:    sha256 $new_sha ($new_size bytes)"
echo "recorded: sha256 $recorded_sha ($recorded_size bytes)"

if [ "$mode" = "check" ]; then
  if [ "$new_sha" = "$recorded_sha" ] && [ "$new_size" = "$recorded_size" ]; then
    echo "OK: rebuild matches PROVENANCE.md"
  else
    echo "MISMATCH: rebuild differs from the pinned binary" >&2
    exit 1
  fi
  exit 0
fi

install -m 755 "$built" "$BIN"

if [ "$new_sha" != "$recorded_sha" ] || [ "$new_size" != "$recorded_size" ]; then
  echo "MISMATCH: rebuilt $new_sha ($new_size bytes) != recorded $recorded_sha ($recorded_size bytes)" >&2
  echo "the toolchain/profile differs from the recorded one; verify the binary in" >&2
  echo "the ACP container (glibc) before re-pinning with --update-provenance" >&2
  exit 1
fi

echo "OK: installed $BIN (matches PROVENANCE.md)"

if [ "$mode" = "update" ]; then
  today="$(date -u +%Y-%m-%d)"
  mb="$(awk -v n="$new_size" 'BEGIN { printf "%.1f", n / 1048576 }')"
  sed -i \
    -e "s/^- \*\*sha256:\*\*.*/- **sha256:** $new_sha/" \
    -e "s/^- \*\*Raw size:\*\*.*/- **Raw size:** $new_size bytes ($mb MB)/" \
    -e "s/^- \*\*Build date:\*\*.*/- **Build date:** $today/" \
    "$PROV"
  echo "re-pinned PROVENANCE.md: $new_sha, $new_size bytes, $today"
fi
