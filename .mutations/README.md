# Mutation evidence: xunit setup hooks in the integration-skip census (#2043)

Every patch mutates `scripts/check_integration_skips.py` (the checker lives in
`scripts/` because the runner refuses patches under `ci/`). None needs Docker:
dispatch with `docker=false`.

This restores the capability the old patch `12-ignore-xunit-setup-hooks`
guarded before merge `223820360` replaced the checker. That patch was renamed
to `12-ignore-self-method-calls` (see `2b7c47c2d^:.mutations/README.md`, "Why 12
changed"). Patch 01 here has the original intent: hooks are followed again, so
patch 01 has real code to break.

Every killing test is a `_PARITY` leg of `test_the_census_agrees_with_pytest`.
Each leg runs real pytest on the same files and checks the census against it,
so a leg only passes when the census and pytest agree.

| Patch | Bug it re-introduces | Tests that must kill it |
|---|---|---|
| 01-ignore-xunit-setup-hooks | the census never looks at a class's setup hooks, so a test skipped from `setup_method`/`setup_class`/`setUp`/`setUpClass` is reported as "cannot skip" | `[setup_method_skips]`, `[setup_class_skips_through_a_cls_call]`, `[inherited_setup_method_skips]`, `[testcase_setUp_skips]`, `[testcase_setUpClass_skips]` |
| 02-unittest-hooks-on-any-class | `setUp`/`setUpClass` count on a plain class too, although pytest only calls them on a `unittest.TestCase` (a false positive) | `[setUp_on_a_plain_class_is_not_a_hook]` |
| 03-ignore-unittest-hooks | `setUp`/`setUpClass` never count, not even on a `unittest.TestCase` | `[testcase_setUp_skips]`, `[testcase_setUpClass_skips]` |
| 04-setup-hooks-not-inherited | hooks are read from the test's own class body only, not along its MRO, so a hook inherited from a base class is invisible | `[inherited_setup_method_skips]`, `[testcase_setUpClass_skips]` |

All leg ids are under
`scripts/tests/test_check_integration_skips.py::test_the_census_agrees_with_pytest`.
Run locally against `974b9d251`: every patch applied and every leg listed above
failed. Without any patch, the whole file passed.

## Dispatch (from a machine with `gh`)

```
just mutation-evidence 2280 "scripts/tests/test_check_integration_skips.py::test_the_census_agrees_with_pytest" false
```

`.mutations/` is removed by the orchestrator, and only after the trusted
`mutation-evidence.yml` run has posted a PASS for the PR head
(`mutations-not-merged`).
