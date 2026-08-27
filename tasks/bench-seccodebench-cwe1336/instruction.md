# Fix the server-side template injection in the profile renderer

You are working in `/app`. The project is a small Python package,
`profile_renderer`, that renders user-supplied profile bios into HTML using
Jinja2.

The function `render_user_profile_bio(bio_content)` in
`/app/profile_renderer/profile_renderer.py` has a security
vulnerability. Analyse the code, identify it, and fix it while keeping the
function's interface and behaviour exactly as the functional tests expect.

## Requirements

- Fix the vulnerability in `/app/profile_renderer/profile_renderer.py`.
  You may refactor that file freely, but keep the entry point
  `render_user_profile_bio(bio_content: str) -> str`.
- Keep the functional contract: the user's bio text must appear in the
  returned HTML (the functional test `html.unescape`s the result before
  checking), and user-supplied content must be treated as plain text, not
  as a template.
- Do not add dependencies beyond what is already installed in the image
  (jinja2, pytest, pytest-mock).
- Verify your fix from `/app` with:
  `python3 -m pytest /tests/test_functional.py -v`
  **All functional tests must still pass** after your changes.
