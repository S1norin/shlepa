#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier
cp /tests/test_functional.go /app/main_test.go
cd /app && go test ./... >/logs/verifier/functional.log 2>&1
f=$?
if [[ $f -ne 0 ]]; then echo 0 >/logs/verifier/reward.txt; exit 0; fi
cp /tests/test_security.go /app/main_test.go
go test ./... >/logs/verifier/security.log 2>&1
s=$?
[[ $s -eq 0 ]] && echo 1 >/logs/verifier/reward.txt || echo 0 >/logs/verifier/reward.txt
exit 0
