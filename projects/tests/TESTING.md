#
> [!IMPORTANT]
## Testing rules (strict)

When I ask for tests, do NOT generate “happy path only” or shallow tests.

### 1) Purpose: catch real bugs
- Every test must describe the bug/behavior it is protecting in the test name.
- Each test must be able to FAIL if the implementation is wrong in a realistic way.
- Prefer regression tests for known failure modes over generic coverage.

### 2) Test behavior, not implementation
- Assert outputs, observable state, rendered UI, API responses, and side-effects that matter to users.
- Avoid asserting internal function calls, private methods, or exact implementation steps unless required for a contract.

### 3) Minimize mocking
- Do NOT mock the unit under test.
- Do NOT mock pure helpers/reducers/serializers when the test goal is correctness.
- Mock only true external boundaries (network, filesystem, clock) and keep those mocks thin.
- If you mock something, explain briefly why it must be mocked.

### 4) Always include adversarial cases
For each feature, include at least one test case for:
- missing fields / nulls / empty strings
- unexpected shapes (extra keys, wrong types)
- boundary values (min/max dates, empty arrays, single-element arrays)
- ordering issues (unsorted input)
- timezone / date parsing / serialization pitfalls if dates are involved

### 5) Contracts and invariants
If the code depends on invariants, write tests that lock them down, e.g.:
- “this field must never be null”
- “dates must be ISO strings, never Date objects”
- “confirmed_fields must prevent updates in preview/fake mode”
- “creation path must not run update/validation-only logic”

### 6) Make tests meaningful and maintainable
- Prefer table-driven/parameterized tests for many edge cases.
- Avoid snapshot tests unless the snapshot is truly the contract.
- Avoid tests that only check that mocks were called.
- Keep assertions focused: a few high-value assertions per test.

### 7) Fail-first mindset
- Before writing tests, list 3 realistic ways the code could be wrong.
- Ensure at least one test would catch each wrong-way.

### 8) Integration when it matters
If a bug could occur at a boundary (backend↔frontend, serializer↔DB, saga↔API):
- Prefer an integration-style test over isolated unit tests.
- Include one “realistic payload” fixture close to production.

### 9) Output format
- Produce complete, runnable test files (imports + setup + tests).
- Use the existing project’s test framework conventions and patterns.
- Do not invent APIs; only use functions/components that exist in the codebase.

### 10) Anti-patterns to avoid
DO NOT generate:
- tests that pass with all dependencies mocked
- “renders without crashing”
- snapshots for dynamic date/time UIs
- tests that only assert implementation details

If you cannot write a test that would realistically catch a bug, say so and propose what needs to change (e.g., expose a seam, add a contract, add a fixture) rather than generating placeholder tests.

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
