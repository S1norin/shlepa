#!/bin/bash
set -euo pipefail

REPORT=/app/flag.txt
REWARD=/logs/verifier/reward.txt
EXPECTED="ca3412b55940568c5b10a616fa7b855e"

mkdir -p "$(dirname "$REWARD")"

fail() {
  echo 0 >"$REWARD"
  exit 0
}

[[ -f "$REPORT" ]] || fail

got="$(tr -d '[:space:]' <"$REPORT")"

if [[ "$got" == "$EXPECTED" ]]; then
  echo 1 >"$REWARD"
else
  echo 0 >"$REWARD"
fi
exit 0
