# Mutation evidence for #1661 slice 2a

Tests: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice_process_manager.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-replay-reopens-delivered.patch` | `handle_event` saves the record unconditionally, so a replayed event overwrites a delivered record as owed | `test_replaying_after_delivery_delivers_nothing` |
| `02-failed-delivery-marked-delivered.patch` | `process_pending` falls through after the sink raised and marks the record delivered | `test_a_refused_delivery_stays_owed_and_the_next_pass_delivers_it_once` |

Both were killed in a local run before pushing (no Docker needed: `docker=false`).
