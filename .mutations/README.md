# Mutation evidence: integration-skip checker (PC-192/PC-193)

Every patch mutates `scripts/check_integration_skips.py` (the checker lives in
`scripts/` because the runner refuses patches under `ci/`). None needs Docker:
dispatch with `docker=false`.

| Patch | Bug it re-introduces | Test that must kill it |
|---|---|---|
| 01-ignore-skipping-fixtures | fixtures are not followed, so a conftest store fixture that skips is invisible | `scripts/tests/test_check_integration_skips.py::test_a_skip_in_a_conftest_fixture_fails` |
| 02-marker-without-issue-is-accepted | `may_skip` with no `issue` counts as a declaration | `scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_fails` |
| 03-ignore-pytest-skip-calls | `pytest.skip(...)` / `pytest.importorskip(...)` in a body is not a skip | `scripts/tests/test_check_integration_skips.py::test_a_skip_in_the_body_without_the_marker_fails` |
| 04-ignore-autouse-fixtures | an autouse fixture that skips is invisible | `scripts/tests/test_check_integration_skips.py::test_an_autouse_or_usefixtures_fixture_that_skips_fails` |
| 05-ignore-parametrized-integration | `pytest.param(..., marks=pytest.mark.integration)` does not make a test integration | `scripts/tests/test_check_integration_skips.py::test_integration_applied_through_a_parametrized_fixture_counts` |
| 06-issue-need-not-be-a-reference | any non-empty string is accepted as `issue` | `scripts/tests/test_check_integration_skips.py::test_an_issue_that_is_not_a_literal_reference_fails` |
| 07-ignore-skip-marks-inside-params | a skip mark inside `pytest.param(..., marks=...)` is invisible | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[parameter_skip_mark]` |
| 08-ignore-fixture-name-kwarg | `@pytest.fixture(name=...)` is indexed by its Python name, not the name pytest registers | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[renamed_fixture]` |
| 09-ignore-class-fixtures | a fixture defined in the test's class is not resolved | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[class_fixture]` |
| 10-ignore-pytest-module-alias | `import pytest as pt; pt.skip(...)` is not a skip | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[pytest_module_alias]` |
| 11-stop-at-reexports | a helper re-exported from a package `__init__` is not followed | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[package_reexport]` |
| 12-ignore-xunit-setup-hooks | `setup_method` (and the other xunit setup hooks) are not followed | `scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[setup_method]` |

Dispatch (from a machine with `gh`):

```
just mutation-evidence 1982 "scripts/tests/test_check_integration_skips.py::test_a_skip_in_a_conftest_fixture_fails scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_fails scripts/tests/test_check_integration_skips.py::test_a_skip_in_the_body_without_the_marker_fails scripts/tests/test_check_integration_skips.py::test_an_autouse_or_usefixtures_fixture_that_skips_fails scripts/tests/test_check_integration_skips.py::test_integration_applied_through_a_parametrized_fixture_counts scripts/tests/test_check_integration_skips.py::test_an_issue_that_is_not_a_literal_reference_fails scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[parameter_skip_mark] scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[renamed_fixture] scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[class_fixture] scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[pytest_module_alias] scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[package_reexport] scripts/tests/test_check_integration_skips.py::test_a_skip_pytest_reaches_without_a_marker_fails[setup_method]" false
```

Delete `.mutations/` before merge (`mutations-not-merged`).
