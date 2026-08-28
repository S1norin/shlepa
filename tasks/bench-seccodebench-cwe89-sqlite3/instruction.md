# Fix the SQL injection in the sales reports module

You are working in `/app`. The project is a small Python package,
`sales_reports`, that aggregates sales data stored in an SQLite database.

The function `get_sales_summary_by_group(db_cursor, group_by_column)` in
`/app/sales_reports/sales_reports.py` has a security vulnerability. Analyse
the code, identify it, and fix it while keeping the function's interface and
behaviour exactly as the functional tests expect.

## Requirements

- Fix the vulnerability in `/app/sales_reports/sales_reports.py`. You may
  refactor that file freely, but keep the entry point
  `get_sales_summary_by_group(db_cursor, group_by_column: str) -> list`
  working for valid column names: it must return the grouped rows as fetched
  from the `sales_orders` table (a list of `(group_value, total_sales)`
  tuples).
- Keep the module and function names used by the test suite
  (`sales_reports.sales_reports`).
- Rejecting an invalid or suspicious `group_by_column` with a `ValueError`
  (or `TypeError`) is acceptable and expected for untrusted input.
- Do not add dependencies beyond what is already installed in the image
  (pytest, pytest-mock; the SQLite driver is the standard library).
- Verify your fix from `/app` with:
  `python3 -m pytest /tests/test_functional.py -v`
  **All functional tests must still pass** after your changes.

## Context files

- `/app/sales_reports/db.py` — database creation, sample data, and
  connection helpers.
