# Mutation patches: placement plan PR 2 (reap scope + reap-before-close)

| patch | re-introduces | killed by |
|---|---|---|
| `01-drop-reap-scope-from-fence.patch` | `fence_expired` accepts any epoch-compatible reconciler | `packages/syn-adapters/tests/test_reap_scope_postgres.py::test_an_executor_in_another_reap_scope_never_fences_an_expired_run` (B fences), `::test_a_run_with_no_live_executor_in_its_scope_stays_charged`, `::test_a_pre_scope_expired_claim_is_scoped_only_by_a_successor_in_its_own_container` |
| `02-drop-reap-before-close-gate.patch` | the host closes a drained run without asking its reaper | `packages/syn-adapters/tests/test_reap_scope_postgres.py::test_a_drain_that_returns_normally_over_unreleased_resources_leaves_the_slot_charged`, `::test_uncertain_delete_keeps_the_slot_until_reap_confirms`, `packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py::test_a_drained_run_whose_resources_are_not_shown_released_is_never_closed` |

The Postgres tests need the Docker-backed runner (`docker=true`).
