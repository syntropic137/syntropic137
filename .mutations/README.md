# Mutation evidence for plan PR 2 (evidence.json)

Delete this directory before merge. Dispatch (sandbox is enough: no Docker needed):

```
just mutation-evidence <pr> "scripts/tests/test_mutation_evidence.py scripts/tests/test_integration_evidence.py" false
```

| Patch | Guard it removes | Killed by |
|---|---|---|
| 01-mutation-skip-reads-as-pass | a skipped baseline charges `skipped` to the requested id | `scripts/tests/test_mutation_evidence.py::test_evidence_json_for_a_void_baseline_never_claims_a_pass` |
| 02-mutation-void-reads-as-failed | a void baseline is `void`, not `failed` | `scripts/tests/test_mutation_evidence.py::test_evidence_json_for_a_void_baseline_never_claims_a_pass` |
| 03-mutation-failure-charged-to-all | a baseline failure is charged only to the id that failed | `scripts/tests/test_mutation_evidence.py::test_evidence_json_charges_a_failure_only_to_the_id_that_failed` |
| 04-integration-requested-skip-ignored | a requested id that did not run and pass voids | `scripts/tests/test_integration_evidence.py::test_a_requested_test_that_did_not_run_and_pass_voids` |
| 05-integration-not-collected-reads-as-pass | an uncollected requested id is `not_collected` | `scripts/tests/test_integration_evidence.py::test_a_requested_test_that_was_never_collected_voids` |
| 06-integration-xpass-reads-as-pass | a non-strict XPASS (a pass in JUnit) is read from `-rX` | `scripts/tests/test_integration_evidence.py::test_a_requested_non_strict_xpass_voids_though_junit_calls_it_a_pass` |
| 07-integration-stops-at-first-failure | the full suite runs, never `-x` | `scripts/tests/test_integration_evidence.py::test_pytest_runs_the_full_suite_without_stopping_early` |
| 08-integration-red-exit-ignored | a run that stopped with nothing on record is void | `scripts/tests/test_integration_evidence.py::test_a_run_that_stopped_with_nothing_on_record_is_void` |
| 09-integration-near-miss-matches | `test_append` does not match `test_append_more` | `scripts/tests/test_integration_evidence.py::test_a_near_miss_name_is_not_the_requested_test` |
| 10-integration-xpass-id-truncated | an XPASS line is matched on the whole node id, spaces included | `scripts/tests/test_integration_evidence.py::test_a_file_selector_never_certifies_an_xpass_whatever_its_parameter` |
| 11-integration-xpass-without-reason-missed | an XPASS line with a ` - reason` still marks the case | `scripts/tests/test_integration_evidence.py::test_a_requested_non_strict_xpass_voids_though_junit_calls_it_a_pass` |
| 12-integration-dotted-selector-match | selectors match exact node ids, not dotted JUnit addresses | `scripts/tests/test_integration_evidence.py::test_a_deselected_file_cannot_borrow_a_pass_from_a_same_named_directory` |
| 13-integration-mangle-rewrites-params | `mangle` leaves `[params]` verbatim, as pytest does | `scripts/tests/test_integration_evidence.py::test_mangle_matches_pytest_junit_addresses` |
| 14-integration-junit-loses-file | pytest writes xunit1 JUnit, which keeps each testcase's `file` | `scripts/tests/test_integration_evidence.py::test_a_class_function_and_parameter_selector_still_select` |
| 15-integration-unidentified-case-ignored | a case with no recoverable node id can still make a selector worse | `scripts/tests/test_integration_evidence.py::test_a_case_whose_file_does_not_fit_can_still_make_a_selector_worse` |

Each was applied locally and killed by the named test (applied one at a time, both test modules run).
