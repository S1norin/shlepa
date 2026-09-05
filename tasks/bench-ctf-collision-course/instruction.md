You are working in `/app/challenge`. A synthetic database was transformed by
`encrypt_database.py`: row IDs were hashed with a three-character salt and
truncated, their original values were concatenated into a cipher password, and
the flag was written to `password.bin` using `my_aes.py`.

All IDs are decimal integers from 1 through 500. Analyze the scripts and
artifacts, recover the salt and original IDs, decrypt the planted flag, and
write it as one line to `/app/flag.txt`. PyCryptodome is installed; runtime is
fully offline.
