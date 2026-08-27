#!/bin/bash
# Reference solution for bench-ctf-target-practice (documentation only —
# the dev engine never runs this file).
#
# The binary is a non-PIE x86-64 ELF (not stripped). main() reads a hex
# number from stdin and jumps to it; cat_flag() runs `cat /flag.txt`.
# Feed the address of cat_flag to the program.
set -euo pipefail

# Any of these reveals the address (0x400717 for the shipped binary):
#   nm /app/target_practice | grep cat_flag
#   objdump -d /app/target_practice | grep -A2 '<cat_flag>'

addr="$(nm /app/target_practice | awk '$3 == "cat_flag" {print $1}')"
[[ -n "$addr" ]] || { echo "cat_flag not found in /app/target_practice" >&2; exit 1; }
echo "$addr" > /app/answer.txt

# Running it with that address prints the flag:
printf '%s\n' "$addr" | /app/target_practice
