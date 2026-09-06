#!/usr/bin/env bash
set -euo pipefail
grep -rho 'flag{[^}]*}' /app/site/private-backups > /app/flag.txt
