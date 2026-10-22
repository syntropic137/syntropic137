# Mutation evidence for #1734 PR 2 (reap scope + reap-before-close)

Each patch re-introduces one defect in production source. The named tests are
integration-marked (real Postgres), so run with Docker (the default).

| patch | defect | killed by |
|---|---|---|
| 01-fence-ignores-reap-scope.patch | `fence_expired` without the scope predicate: B (other scope) fences | `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_an_executor_in_another_reap_scope_never_fences_an_expired_run`, `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_run_with_no_live_executor_in_its_scope_stays_charged` |
| 02-takeover-ignores-reap-scope.patch | `take_over` without the scope predicate | `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_takeover_requires_the_same_reap_scope` |
| 03-close-without-reap-gate.patch | the host closes without the reap-before-close gate | `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_drain_that_returns_normally_over_unreleased_resources_leaves_the_slot_charged`, `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_uncertain_delete_keeps_the_slot_until_reap_confirms` |
| 04-no-same-container-backfill.patch | `register` never scopes a pre-scope row | `packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_pre_scope_expired_claim_is_scoped_only_by_a_successor_in_its_own_container` |

Dispatch:

```
just mutation-evidence 2072 "packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_an_executor_in_another_reap_scope_never_fences_an_expired_run packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_run_with_no_live_executor_in_its_scope_stays_charged packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_takeover_requires_the_same_reap_scope packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_drain_that_returns_normally_over_unreleased_resources_leaves_the_slot_charged packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_uncertain_delete_keeps_the_slot_until_reap_confirms packages/syn-adapters/tests/test_execution_run_queue_postgres.py::test_a_pre_scope_expired_claim_is_scoped_only_by_a_successor_in_its_own_container"
```
