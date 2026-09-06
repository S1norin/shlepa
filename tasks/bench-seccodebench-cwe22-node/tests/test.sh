#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier /app/test
cp /tests/function.test.js /app/test/function.test.js
cd /app && npx jest test/function.test.js --runInBand >/logs/verifier/functional.log 2>&1
f=$?
if [[ $f -ne 0 ]]; then echo 0 >/logs/verifier/reward.txt; exit 0; fi
cp /tests/security.test.js /app/test/security.test.js
npx jest test/security.test.js --runInBand >/logs/verifier/security.log 2>&1
s=$?
[[ $s -eq 0 ]] && echo 1 >/logs/verifier/reward.txt || echo 0 >/logs/verifier/reward.txt
exit 0
