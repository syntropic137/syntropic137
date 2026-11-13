# Mutation evidence added by fix round 1 (#2043, PR #2280)

Two more patches for the two defects verification found on `86c0d66c6`. The
README beside this file is unchanged and still describes patches 01-04, which
apply unchanged to the repaired checker. The fixture rule was placed in
`_Module._methods` so that their context still matches.

| Patch | Bug it re-introduces | Tests that must kill it |
|---|---|---|
| 05-fixtures-count-as-setup-hooks | a fixture named `setup_method`/`setup_class` is treated as the xunit hook (pytest never calls it as one), and a fixture is treated as a `self.` callee (pytest refuses a direct call) | `[a_setup_method_fixture_is_not_a_hook]`, `[a_setup_class_fixture_is_not_a_hook]`, `[a_fixture_called_through_self_is_not_a_method]` |
| 06-unittest-base-by-spelling | a class is taken as `unittest.TestCase` because its base's name ends in `TestCase`, not because it is one: an aliased `TestCase` is missed and an imported `StoreTestCase` impostor counts | `[aliased_testcase_setUp_skips]`, `[a_testcase_suffix_is_not_unittest]` |

All leg ids are under
`scripts/tests/test_check_integration_skips.py::test_the_census_agrees_with_pytest`.
Run locally: every patch from 01 to 06 applied and each failed the legs listed
for it (and others). Without any patch, the whole test passed.

Dispatch is the same as in README.md:

```
just mutation-evidence 2280 "scripts/tests/test_check_integration_skips.py::test_the_census_agrees_with_pytest" false
```
