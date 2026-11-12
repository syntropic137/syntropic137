# Mutation patches for #1534

| Patch | Re-introduces | Killed by |
|---|---|---|
| `01-handler-ignores-guard.patch` | the handler schedules even when it does not hold the run's guard (main's behaviour) | `packages/syn-adapters/tests/test_1534_inventory_scheduling_guard.py::test_two_managers_racing_one_run_open_exactly_one_job`, `::test_a_run_whose_guard_is_held_is_skipped_and_its_wakeup_kept`, `::test_two_managers_on_postgres_open_exactly_one_job_per_run` |
| `02-postgres-guard-always-grants.patch` | the Postgres guard reports "held" without the advisory lock | `packages/syn-adapters/tests/test_1534_inventory_scheduling_guard.py::test_two_managers_on_postgres_open_exactly_one_job_per_run` (integration, needs Docker) |
