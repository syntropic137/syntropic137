# Mutation evidence for #1965

U = packages/syn-adapters/tests/test_1965_run_queue_schema_lock.py (unit, killed locally)
I = packages/syn-adapters/tests/test_1965_run_queue_schema_postgres.py (integration, needs Docker)

| Patch | Bug it reintroduces | Killed by |
|---|---|---|
| 01-no-schema-lock | ensure_ready takes no lock | U::test_every_schema_statement_runs_inside_the_run_queue_session_lock, U::test_the_lock_is_released_when_a_step_fails, I::test_two_processes_applying_together_both_succeed_one_at_a_time |
| 02-lock-waited-for-inside-a-transaction | a snapshot is held while waiting for the lock (#1906) | U::test_every_schema_statement_runs_inside_the_run_queue_session_lock, U::test_the_lock_is_released_when_a_step_fails |
| 03-no-ledger-row | steps apply but are not recorded | U::test_each_step_commits_with_its_ledger_row_in_file_order, I::test_applying_twice_on_pre_pool_data_changes_nothing_the_second_time |
| 04-ledger-rewrites-applied-at | a second apply changes the ledger | I::test_applying_twice_on_pre_pool_data_changes_nothing_the_second_time |
| 05-unguarded-constraint | a step that is not idempotent | I::test_applying_twice_on_pre_pool_data_changes_nothing_the_second_time |
| 06-pool-id-without-default | an upgrade that breaks a pre-#1931 image | I::test_an_image_from_before_pools_still_runs_after_the_upgrade |
