# Mutation evidence for #1944 (PR-scoped; delete before merge)

All killing tests are unit tests on the in-memory queue: run with `docker=false`.

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-turn-budget-removed.patch` | claims no longer stop at `turn_budget` | `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_turn_of_slow_claims_stays_within_its_budget` |
| `02-concurrency-unbounded.patch` | every owned row is attempted at once | `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_live_host_reconciling_20_blocked_reaps_never_reads_stale` |
| `03-draining-host-still-adopts.patch` | a draining host still fences, adopts and starts attempts | `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_draining_host_acquires_nothing`, `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_draining_finishes_started_reconciliation_and_leaves_the_rest` |
| `04-heartbeat-at-turn-start-only.patch` | the pre-fix turn shape: the heartbeat is the only liveness write and the turn then awaits the sweep and every reap inline | `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_live_host_reconciling_20_blocked_reaps_never_reads_stale`, `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_reconciling_host_still_claims_new_work`, `packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_blocked_opening_sweep_does_not_stop_the_loop` |
| `05-execution-id-order.patch` | attempts in `execution_id` order, not least recently attempted | `packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py::test_rows_whose_reaps_keep_failing_do_not_starve_the_rows_behind_them` |

Dispatch:

```
just mutation-evidence 1975 "packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_turn_of_slow_claims_stays_within_its_budget packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_live_host_reconciling_20_blocked_reaps_never_reads_stale packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_draining_host_acquires_nothing packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_draining_finishes_started_reconciliation_and_leaves_the_rest packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_reconciling_host_still_claims_new_work packages/syn-adapters/src/syn_adapters/execution_host/test_host_liveness.py::test_a_blocked_opening_sweep_does_not_stop_the_loop packages/syn-adapters/src/syn_adapters/execution_host/test_execution_host.py::test_rows_whose_reaps_keep_failing_do_not_starve_the_rows_behind_them" false
```

Each patch was applied locally in this workspace and its listed tests failed;
the unpatched baseline passes.
