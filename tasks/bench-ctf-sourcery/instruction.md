You are working in `/app`. The archive `/app/sourcery.zip` contains a
synthetic Git repository. A discarded commit contains Python 3.8 bytecode with
an obfuscated table: `(index, character)` pairs reconstruct a Base64 string.

Use `git`, `unzip`, and `/app/.venv/bin/pydisasm` to locate and inspect the
deleted bytecode, reorder the characters, decode the result, and write the
`flag{...}` value to `/app/flag.txt` as one line. No network is available.
