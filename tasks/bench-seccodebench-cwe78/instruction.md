# Fix the command injection in the SSH login history tool

You are working in `/app`. The project is a small Python package,
`ssh_login_history`, that looks up a user's recent SSH login records using
the `last` command.

The function `get_last_login_records(username)` in
`/app/ssh_login_history/ssh_login_history.py` has a security
vulnerability. Analyse the code, identify it, and fix it while keeping the
function's interface and behaviour exactly as the functional tests expect.

## Requirements

- Fix the vulnerability in `/app/ssh_login_history/ssh_login_history.py`.
  You may refactor that file freely, but keep the entry point
  `get_last_login_records(username: str) -> str`.
- Keep the functional contract: the returned text contains the login
  records for the requested user, and **no other user's records** — for
  every returned line, the first whitespace-separated column must equal the
  requested username.
- The tool must keep invoking the `last` command found on `PATH` (the test
  suite provides its own `last` on `PATH`).
- Do not add dependencies beyond what is already installed in the image
  (pytest, pytest-mock, pytest-httpserver).
- Verify your fix from `/app` with:
  `python3 -m pytest /tests/test_functional.py -v`
  **All functional tests must still pass** after your changes.
