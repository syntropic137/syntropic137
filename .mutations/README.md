# Mutation evidence for #1661 slice 2a

Tests: `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice_process_manager.py`, and for `04` `.../slices/notify_quarantine/test_quarantine_notice.py`

| Patch | Bug re-introduced | Killed by |
|---|---|---|
| `01-replay-reopens-delivered.patch` | `handle_event` saves the record unconditionally, so a replayed event overwrites a delivered record as owed | `test_replaying_after_delivery_delivers_nothing` |
| `02-failed-delivery-marked-delivered.patch` | `process_pending` falls through after the sink raised and marks the record delivered | `test_a_refused_delivery_stays_owed_and_the_next_pass_delivers_it_once` |
| `03-idempotency-key-defaults-empty.patch` | The record's `key` is not dumped into the stored row, and `get_idempotency_key` falls back to `""` | `test_each_stored_row_carries_its_own_idempotency_key` |
| `04-quarantine-idempotency-key-defaults-empty.patch` | The same, for `QuarantineNotice` and `QuarantineNoticeProcessManager` | `test_each_stored_row_carries_its_own_idempotency_key` (quarantine) |
| `05-unreadable-row-suppresses-delivery.patch` | `handle_event` treats any row under the key, readable or not, as already recorded | `test_an_unreadable_row_under_the_key_is_replaced_and_delivered_once` |

All were killed in a local run before pushing (no Docker needed: `docker=false`).

`03` and `04` restore both halves of the original defect. Restoring only the
`""` default is an equivalent mutant: once the row carries `key`, `.get("key", "")`
and `["key"]` return the same value, so no test can kill it.
