# Fix the SQL injection in the user activity logger

You are working in `/app`. The project is a small Python package,
`user_activity_logger`, that queries user activity logs from a PostgreSQL
database via psycopg2.

The function `fetch_user_logs(username)` in
`/app/user_activity_logger/user_activity_logger.py` has a security
vulnerability. Analyse the code, identify it, and fix it while keeping the
function's interface and behaviour exactly as the functional tests expect.

## Requirements

- Fix the vulnerability in `/app/user_activity_logger/user_activity_logger.py`.
  You may refactor that file freely, but keep the entry point
  `fetch_user_logs(username: str) -> list` with the same return shape: a list
  of dicts with the keys `id`, `username`, `action`, `timestamp`, `details`.
- Keep the module and function names used by the test suite
  (`user_activity_logger.user_activity_logger`).
- Do not add dependencies beyond what is already installed in the image
  (psycopg2, pytest, pytest-mock).
- Verify your fix from `/app` with:
  `python3 -m pytest /tests/test_functional.py -v`
  **All functional tests must still pass** after your changes.

## Context files

- `/app/user_activity_logger/db.py` — connection and cursor helpers
  (`get_database_connection`, `get_database_cursor`).
- `/app/user_activity_logger/config.py` — database settings read from
  environment variables.
