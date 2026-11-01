# Testing and Continuous Integration

## Local checks

Create and install the project development environment as described in the
[README](../README.md), then run the same checks as CI:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m black --check .
```

The test fixtures create ephemeral SQLite databases, including attached
`yottaflex` and `yottaflex_eval` schemas. The automated test suite does not
require live MySQL, database credentials, or a local `.env` file.

## GitHub Actions

The workflow in `.github/workflows/ci.yml` runs for pushes and pull requests.
It tests Python 3.11 and 3.13 in separate Ubuntu jobs, installs
`requirements-dev.txt`, and runs pytest, Ruff, and Black. Any failed command
fails its job. The workflow requests read-only repository contents permission
and does not use secrets or modify application, production database, or grant
configuration.

CI validates the SQLite-based automated suite; it does not replace separate
MySQL integration checks, migration verification, or live database-grant
verification.
