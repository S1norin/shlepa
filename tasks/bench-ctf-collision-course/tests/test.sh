#!/usr/bin/env bash
set -euo pipefail
mkdir -p /logs/verifier
if [[ -f /app/flag.txt ]] && [[ "$(tr -d '\r\n' </app/flag.txt)" == 'flag{d0nt_g3t_2_s4lty}' ]]; then
  echo 1 >/logs/verifier/reward.txt
else
  echo 0 >/logs/verifier/reward.txt
fi
exit 0
