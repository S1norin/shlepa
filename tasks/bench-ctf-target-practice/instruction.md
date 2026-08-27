You are working in `/app`. The file `/app/target_practice` is a CTF "pwn" challenge binary.

The program reads one hex number from standard input and jumps to it, treating it as the address of a function. Somewhere inside the binary there is a function that prints the CTF flag; it is only reachable by jumping to it.

Reverse-engineer the binary (`nm` and `objdump` are available), find the address of that function, and write **the address in hexadecimal** (a single line, `0x` prefix optional) to `/app/answer.txt`.

The verifier re-runs a pristine copy of the binary with your address and checks that the flag is printed.
