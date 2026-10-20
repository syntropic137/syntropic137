# Mutation evidence: integration-skip checker (PC-192/PC-193)

Every patch mutates `scripts/check_integration_skips.py` (the checker lives in
`scripts/` because the runner refuses patches under `ci/`). None needs Docker:
dispatch with `docker=false`.

The patches were regenerated against `c7ec6dc5f`. The earlier set targeted the
checker this PR first wrote; merge `223820360` replaced that checker and its
test file with main's implementation, so none of the old patches applied and
none of the old killing tests exist any more (run 39364960460: 12 x APPLY FAILED).
Each patch keeps its original intent, expressed against the current code. The
exception is 12.

| Patch | Bug it re-introduces | Test that must kill it |
|---|---|---|
| 01-ignore-skipping-fixtures | `_Scope.fixture_skips` never looks at a fixture, so a skip reached through any requested fixture is invisible | `scripts/tests/test_check_integration_skips.py::test_a_fixture_in_a_parent_conftest_behind_another_fixture` |
| 02-marker-without-issue-is-accepted | `may_skip` with no `issue` keyword counts as a declaration (a present but malformed `issue` is still refused, so this is distinct from 06) | `scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_is_malformed` |
| 03-ignore-pytest-skip-calls | `pytest.skip(...)` / `pytest.importorskip(...)` written as an attribute call is not a skip (a bare `skip()` from `from pytest import skip` still is) | `scripts/tests/test_check_integration_skips.py::test_a_skip_without_the_marker_is_found` |
| 04-ignore-autouse-fixtures | `_Scope.autouse` returns nothing, so an autouse fixture that skips is invisible | `scripts/tests/test_check_integration_skips.py::test_an_autouse_fixture_counts` |
| 05-ignore-parametrized-integration | `pytest.param(..., marks=pytest.mark.integration)` does not make a leg integration; only the test's own marks do | `scripts/tests/test_check_integration_skips.py::test_an_integration_leg_of_a_parametrize_counts` |
| 06-issue-need-not-be-a-reference | any non-empty string is accepted as `issue` | `scripts/tests/test_check_integration_skips.py::test_an_opt_out_needs_a_named_reason_and_a_hash_issue` |
| 07-ignore-skip-marks-inside-params | a `skip`/`skipif` inside `pytest.param(..., marks=...)` is invisible; only the test's own marks count | `scripts/tests/test_check_integration_skips.py::test_a_parameter_skipif_on_an_integration_test_counts` |
| 08-ignore-fixture-name-kwarg | `@pytest.fixture(name=...)` is indexed by its Python name, not the name pytest registers | `scripts/tests/test_check_integration_skips.py::test_a_fixture_requested_by_its_name_override_counts` |
| 09-ignore-class-fixtures | a test's class (and its same-module bases) contribute no fixtures | `scripts/tests/test_check_integration_skips.py::test_an_inherited_fixture_that_skips_counts` |
| 10-ignore-pytest-module-alias | `import pytest as pt` binds only `pytest`, so `pt.skip(...)` and `pt.mark.*` are not seen | `scripts/tests/test_check_integration_skips.py::test_an_aliased_pytest_module_skips_and_marks` |
| 11-stop-at-reexports | `from x import name` is followed one hop only: a helper re-exported from a package `__init__` is not followed to its definition | `scripts/tests/test_check_integration_skips.py::test_a_skip_in_a_helper_imported_from_another_module_counts` |
| 12-ignore-self-method-calls | `self.`/`cls.` calls are not resolved along the test's class MRO, so a method the test calls that skips is invisible | `scripts/tests/test_check_integration_skips.py::test_self_calls_resolve_in_the_tests_own_class` |

## Why 12 changed

The old 12, `ignore-xunit-setup-hooks`, mutated the old checker's
`_CLASS_SETUP` (`setup_class`, `setup_method`, `setUpClass`, `setUp`).
The current checker has no equivalent: it does not follow xunit setup hooks at
all, so there is no code for that mutation to break. The patch was renamed to
`12-ignore-self-method-calls` because it now tests a different behaviour.

Its replacement targets the nearest code that still exists. A `setup_method`
is a method pytest calls on the test's class, and `_Module._callees` is the
code that resolves methods on the test's class (`self.`/`cls.` through its
MRO). The replacement does NOT test xunit hooks. It cannot, because the census
no longer sees them.

**This is a lost capability, not just a moved target.** An integration test
whose class has a `setup_method` that calls `pytest.skip()` is skipped by
pytest, but the census does not report it. The census undercounts that shape, and
no test (including `test_the_census_agrees_with_pytest`) covers it. Restoring it
means changing `scripts/`, which this regeneration round was forbidden to do.
It is tracked in #2043.

## Dispatch (from a machine with `gh`)

```
just mutation-evidence 1982 "scripts/tests/test_check_integration_skips.py::test_a_fixture_in_a_parent_conftest_behind_another_fixture scripts/tests/test_check_integration_skips.py::test_a_marker_without_an_issue_is_malformed scripts/tests/test_check_integration_skips.py::test_a_skip_without_the_marker_is_found scripts/tests/test_check_integration_skips.py::test_an_autouse_fixture_counts scripts/tests/test_check_integration_skips.py::test_an_integration_leg_of_a_parametrize_counts scripts/tests/test_check_integration_skips.py::test_an_opt_out_needs_a_named_reason_and_a_hash_issue scripts/tests/test_check_integration_skips.py::test_a_parameter_skipif_on_an_integration_test_counts scripts/tests/test_check_integration_skips.py::test_a_fixture_requested_by_its_name_override_counts scripts/tests/test_check_integration_skips.py::test_an_inherited_fixture_that_skips_counts scripts/tests/test_check_integration_skips.py::test_an_aliased_pytest_module_skips_and_marks scripts/tests/test_check_integration_skips.py::test_a_skip_in_a_helper_imported_from_another_module_counts scripts/tests/test_check_integration_skips.py::test_self_calls_resolve_in_the_tests_own_class" false
```

`.mutations/` is removed by the orchestrator, and only after the trusted
`mutation-evidence.yml` run has posted a PASS for the PR head
(`mutations-not-merged`).
