# Mutation patches for #2321 slice A

Named tests: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/execute_workflow/test_2321_workspace_retained_recorded.py apps/syn-api/tests/test_2321_retained_workspace_recorded.py` (no Docker: `docker=false`).

| Patch | Bug it re-introduces | Killed by |
|---|---|---|
| 02 | the startup orphan guard keeps but records nothing | `test_an_orphan_kept_at_startup_is_recorded_and_only_the_clean_one_is_cleared` |
| 03 | every reclaim pass appends another event for the same keep | `test_a_pass_that_keeps_it_again_adds_nothing_even_after_a_restart` |
| 04 | the phase is not read off the execution's stream | `test_a_kept_workspace_is_one_event_naming_its_phase_and_reason`, `test_an_orphan_kept_at_startup_is_recorded_and_only_the_clean_one_is_cleared` |
| 05 | a recording failure raises into the guard | `test_an_orphan_whose_record_fails_is_still_kept`, `test_a_recording_failure_never_raises_into_the_guard` |
| 06 | orphan submodule work is named as a refused push | `test_each_orphan_keep_names_its_reason[submodule-work]` |
| 07 | a `None` phase_id cannot be read back (the serialiser omits it) | `test_a_workspace_the_stream_never_provisioned_names_no_phase` |
| 08 | an orphan whose quarantine push was refused is cleared | `test_each_orphan_keep_names_its_reason[push-refused]` |


01 was withdrawn with the reclaimer wiring it mutated (the janitor may not write the event store, #1983); it never had an evidence run.
