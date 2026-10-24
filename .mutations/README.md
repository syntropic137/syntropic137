# Mutation evidence for #1511

| Patch | Bug it re-introduces | Test that kills it |
|---|---|---|
| 01-abort-drops-cause | abort message without the exception | apps/syn-api/tests/test_inventory_recovery_lifecycle.py::test_startup_abort_names_the_inventory_failure_cause |
| 02-stage-overwrites-live | `stage` writes over the live compose | scripts/tests/test_pit_stop_stage_write.py::test_a_whole_transfer_stages_beside_the_live_compose_and_the_swap_applies_it |
| 03-drift-never-refuses | `--drift` exits 0 on a real diff | scripts/tests/test_pit_stop_repoint.py::TestDrift::test_config_the_deployed_file_lacks_is_drift |
| 04-apply-skips-staleness-check | swap moves a stale staged file over a newer live edit | scripts/tests/test_pit_stop_stage_write.py::test_the_swap_refuses_a_stage_the_live_compose_has_moved_past |
| 05-stage-skips-drift-recheck | `stage` repoints a compose edited on the host since the precheck, unchecked | scripts/tests/test_pit_stop_stage_write.py::test_the_stage_refuses_a_compose_edited_on_the_host_since_the_precheck |
| 06-old-asset-as-baseline | an env var swaps `$REF`'s compose for an older baseline that hides the drift | scripts/tests/test_1310_pit_stop_gateway_only.py::TestComposeDrift::test_an_old_release_asset_is_no_baseline |
| 07-apply-reopens-after-write | an ssh failure after the live compose write re-opens admission over new pins the old build still runs | scripts/tests/test_pit_stop_stage_write.py::test_admission_stays_paused_once_the_live_compose_may_have_been_written |
