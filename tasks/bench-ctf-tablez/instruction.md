You are working in `/app`. The file `/app/tablez` is a CTF "rev" challenge binary.

The program reads a single line from standard input, translates every
character of that line through an embedded lookup table, and compares the
translated result against an embedded target string of a fixed length. If
they match, it prints `CORRECT <3` and exits with status 0; otherwise it
prints `WRONG` and exits with status 1.

The program checks a flag in `flag{...}` format: that flag is the input that
makes the program print `CORRECT <3`.

Reverse-engineer the binary (`nm`, `objdump`, `strings`, and `gcc` are
available; there is no network access), recover the flag, and write it to
`/app/flag.txt` (one line).

The verifier re-runs a pristine copy of the binary with the contents of
`/app/flag.txt` and checks that it prints `CORRECT <3`, so modifications you
make to `/app/tablez` itself do not affect the outcome.
