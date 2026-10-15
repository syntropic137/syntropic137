# Mutation evidence for the integration-skip census (#1984)

Each patch re-introduces one defect into `scripts/check_integration_skips.py`.
All six were killed locally (2026-10-15) by the named tests; the runner is the record.

| Patch | Defect | Killed by |
|---|---|---|
| 01-ignore-fixtures.patch | fixtures are never followed | `scripts/tests/test_check_integration_skips.py::test_a_fixture_in_a_parent_conftest_behind_another_fixture`, `scripts/tests/test_check_integration_skips.py::test_a_renamed_autouse_or_usefixtures_fixture_counts` |
| 02-accept-opt-out-without-issue.patch | `may_skip` without a `#N` issue counts as declared | `scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_is_malformed` |
| 03-ignore-skip-markers.patch | `skip`/`skipif` markers are not a skip | `scripts/tests/test_check_integration_skips.py::test_a_module_skipif_marks_every_test` |
| 04-ignore-declarations.patch | a declared skip is still counted | `scripts/tests/test_check_integration_skips.py::test_a_declared_skip_passes` |
| 05-ignore-helper-calls.patch | same-module helpers are not followed | `scripts/tests/test_check_integration_skips.py::test_a_helper_the_test_calls_is_followed` |
| 06-ignore-conftests.patch | conftest fixtures are out of scope | `scripts/tests/test_check_integration_skips.py::test_a_fixture_in_a_parent_conftest_behind_another_fixture` |

Dispatch (no Docker needed):

```
just mutation-evidence 1985 "scripts/tests/test_check_integration_skips.py::test_a_fixture_in_a_parent_conftest_behind_another_fixture scripts/tests/test_check_integration_skips.py::test_a_renamed_autouse_or_usefixtures_fixture_counts scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_is_malformed scripts/tests/test_check_integration_skips.py::test_a_module_skipif_marks_every_test scripts/tests/test_check_integration_skips.py::test_a_declared_skip_passes scripts/tests/test_check_integration_skips.py::test_a_helper_the_test_calls_is_followed" false
```

Delete `.mutations/` before merge (CI job `mutations-not-merged`).
