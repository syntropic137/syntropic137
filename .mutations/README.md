# #2107 / #2128 mutation evidence

Each patch re-introduces one bug in non-test source; the named tests must kill it.
`D` = `packages/syn-adapters/tests/test_deletion_fence_postgres.py` (Postgres integration, needs Docker: `docker=true`).
`R` = `packages/syn-adapters/tests/test_capture_deletion_reasons.py` (unit, no Docker).

| Patch | Bug | Killed by (verified locally, clean head 14/14 pass first) |
|---|---|---|
| 01-automatic-expiry-enqueued | age/quota/default expiry enqueued to the replica again | `D::test_automatic_expiry_never_deletes_the_replica_copy` [retention_age, retention_quota, default]; also promotes x4, checkpointed purge, crash-before-checkpoint, failed-removal |
| 02-owner-deletes-not-enqueued | owner deletion/retraction never reaches the replica | `D::test_owner_deletion_and_retraction_still_delete_the_replica_copy` [deletion, retraction]; `D::test_owner_delete_in_flight_from_an_older_build_is_regenerated`; promotes x4, crash, failed-removal |
| 03-no-promotion-to-owner | owner request on an automatic tombstone keeps the automatic reason | `D::test_owner_request_promotes_an_automatic_tombstone_and_propagates` [pending/completed x deletion/retraction] |
| 04-discard-swallows-removal-failure | outbox removal failure reported as success | `R::test_deletion_outbox_discard_raises_when_an_entry_survives` |
| 05-worker-swallows-failed-purge | failed purge recorded, checkpoint dropped, orphan drained | `D::test_failed_outbox_removal_records_no_purge_and_drains_nothing` |
| 06-purge-disabled | pre-fix outbox never purged | `D::test_checkpointed_automatic_delete_from_an_older_build_is_purged_unsent`; `D::test_crash_between_exporter_enqueue_and_checkpoint_commit_is_purged`; failed-removal |
| 07-purge-keeps-unacked-checkpoints | purge leaves the older build's checkpoint to drain | `D::test_checkpointed_automatic_delete_from_an_older_build_is_purged_unsent` |

No killing test is one of the binary-gated tests that skip without the exporter/SeshMagic binaries.
