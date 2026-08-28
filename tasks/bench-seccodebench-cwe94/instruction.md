# Fix the code injection in the workflow transformer module

You are working in `/app`. The project is a small Python package,
`workflow_transformer`, used by a workflow automation tool to transform
the output of one step into the input of the next.

The function `transform_step_data(transform_map_expr, input_data)` in
`/app/workflow_transformer/workflow_transformer.py` has a security
vulnerability. Analyse the code, identify it, and fix it while keeping the
function's interface and behaviour for valid expressions exactly as the
functional tests expect.

## Requirements

- Fix the vulnerability in
  `/app/workflow_transformer/workflow_transformer.py`. You may refactor that
  file freely, but keep the entry point
  `transform_step_data(transform_map_expr: str, input_data: dict) -> dict`
  working for valid expressions.
- A valid expression is a Python dictionary literal whose values are built
  from:
  - literals (strings, numbers, booleans, `None`),
  - lookups of string keys on `input_data` — keys may contain any
    characters, e.g. `input_data['__class__']`,
  - arithmetic (`+ - * / // %`) and unary minus,
  - comparisons (`== != < <= > >=`), including chained ones,
  - boolean operators (`and`, `or`).
  Examples:
  `{'new_id': input_data['id'], 'value': input_data['value'] * 10}` and
  `{'is_high': input_data['price'] * input_data['factor'] > 550}`.
- Expressions containing anything outside that language — function calls,
  attribute access, names other than `input_data`, subscripts of anything
  other than `input_data`, comprehensions, etc. — must be rejected with
  `ValueError` (or `TypeError`) and must not execute any code.
- Keep the module and function names used by the test suite
  (`workflow_transformer.workflow_transformer`).
- Do not add dependencies beyond what is already installed in the image
  (pytest, pytest-httpserver; the standard library is available).
- Verify your fix from `/app` with:
  `python3 -m pytest /tests/test_functional.py -v`
  **All functional tests must still pass** after your changes.
