# tmp/

Scratch space for development runs. Everything in here is gitignored except
this README.

- `shlepa run` creates a per-task workspace
  `tmp/YYYYMMDD-HHMMSS-<task-slug>/` (workspace files, agent output, the
  per-task result JSON).
- `shlepa submit-test` unzips the built submission into a temporary directory
  here.
- External benchmark clones (for task adaptation work) are also kept here.

Cleanup: `shlepa clean` removes entries older than 7 days.
