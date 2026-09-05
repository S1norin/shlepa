#!/usr/bin/env bash
set -euo pipefail
cd /app/challenge
/app/.venv/bin/python - <<'PY'
import csv, hashlib, itertools, string
import my_aes

rows = list(csv.DictReader(open("encrypted_database.csv")))
alphabet = string.ascii_lowercase + string.digits
for salt_tuple in itertools.product(alphabet, repeat=3):
    salt = "".join(salt_tuple)
    ids = []
    for row in rows:
        matches = [str(i) for i in range(1, 501)
                   if hashlib.md5((str(i) + salt).encode()).hexdigest()[:4] == row["id"]]
        if len(matches) != 1:
            break
        ids.append(matches[0])
    else:
        try:
            flag = my_aes.decrypt_from_file("".join(ids), "password.bin").decode().strip()
        except ValueError:
            continue
        open("/app/flag.txt", "w").write(flag + "\n")
        break
else:
    raise SystemExit("no valid salt found")
PY
