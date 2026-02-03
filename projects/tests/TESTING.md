#
> [!IMPORTANT]
> **ALWAYS check existing tests** (e.g. `projects/tests/test_deadline_lifecycle.py`, `test_deadline_data_completeness.py`) to see how things are done before writing new tests. Do not reinvent the wheel or use brittle mocks if DB tests are better supported.

This document describes how to run tests for the Kaavapino project., you need to use `poetry`. The tests are located in `projects/tests` (and potentially other apps), but `pytest` should be run from the `kaavapino` directory where `pyproject.toml` is located.

## Command

Run the following command from the `kaavapino/` directory:

```bash
poetry run pytest
```

or to run a specific test file:

```bash
poetry run pytest projects/tests/test_deadline_preview_cascade.py
```
