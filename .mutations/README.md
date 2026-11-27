# Mutation patches for #1004 slice 1

Tests named:

- `apps/syn-api/tests/test_1004_execution_detail_serves_commits_over_http.py`
- `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/get_execution_detail/test_1004_recorded_commits_reach_the_read_model.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-phase-commits-dropped.patch` | projection drops each phase's `checked_out_commits` | `test_the_start_and_each_phase_carry_the_commits_they_recorded`, `test_a_retried_phase_carries_its_latest_checkout`, HTTP `test_the_detail_serves_the_run_and_phase_commits` |
| `02-execution-commits-dropped.patch` | projection drops the start's `source_commits` | `test_the_start_and_each_phase_carry_the_commits_they_recorded`, HTTP `test_the_detail_serves_the_run_and_phase_commits` |
| `03-none-coerced-to-empty.patch` | reader turns "not recorded" (None) into `()` | `test_a_run_that_recorded_no_commits_reads_not_recorded_not_empty`, HTTP `test_an_older_run_serves_null_not_an_empty_list` |
| `04-response-drops-execution-commits.patch` | `GET /executions/{id}` response constructor omits `source_commits` | HTTP `test_the_detail_serves_the_run_and_phase_commits` |
| `05-failure-drops-phase-commits.patch` | `PhaseDetail.to_dict` drops `checked_out_commits`, so `WorkflowFailed` erases a failed phase's checkout | `test_a_failed_phase_keeps_the_checkout_it_recorded[recorded]`, `[recorded-empty]`, HTTP `test_a_failed_phase_still_serves_its_checkout` |
| `06-failure-coerces-none-to-empty.patch` | `PhaseDetail.from_dict` turns "not recorded" into `[]` on the failure round trip | `test_a_failed_phase_keeps_the_checkout_it_recorded[not-recorded]` |

Run locally in the implement workspace (not trusted evidence): all four killed.
