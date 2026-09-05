#!/usr/bin/env bash
set -uo pipefail
mkdir -p /logs/verifier /app/src/test/java/com/example
cp /tests/FunctionalTest.java /app/src/test/java/com/example/FunctionalTest.java
cd /app && mvn -q -o -Dtest=FunctionalTest test >/logs/verifier/functional.log 2>&1
f=$?
if [[ $f -ne 0 ]]; then echo 0 >/logs/verifier/reward.txt; exit 0; fi
rm -f /app/src/test/java/com/example/FunctionalTest.java
cp /tests/SecurityTest.java /app/src/test/java/com/example/SecurityTest.java
mvn -q -o -Dtest=SecurityTest test >/logs/verifier/security.log 2>&1
s=$?
[[ $s -eq 0 ]] && echo 1 >/logs/verifier/reward.txt || echo 0 >/logs/verifier/reward.txt
exit 0
