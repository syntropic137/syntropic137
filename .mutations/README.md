# Mutation evidence: remote receipts and replica bodies (Refs #946)

| Patch | Re-introduces | Test meant to kill it |
|---|---|---|
| `01-accept-receipt-for-another-revision.patch` | `publish_capture_receipt` records any receipt with the right storage key as a PRESENT remote replica, without comparing its original-content hash to the archived bytes (`validates_capture` not called) | `packages/syn-adapters/tests/test_capture_receipt_evidence.py::test_duplicate_acknowledgements_replay_identically_and_reject_wrong_identity`, `packages/syn-adapters/tests/test_capture_delivery_worker.py::test_receipt_publication_precedes_checkpoint_and_retries_identically[revision]` |
| `02-accept-empty-replica-body.patch` | `replica_body_availability` returns PRESENT for a stored row with an empty `raw` body when the archive has bytes (both #946 signatures) | `packages/syn-domain/tests/contexts/agent_sessions/test_replica_body_evidence_port.py::test_only_a_stored_raw_body_is_present` |

Local run (no Docker needed): each patch applies with `git apply --check`.
With 01 applied, both mapped tests fail (`DID NOT RAISE` for the publisher;
`append` called once for the worker). With 02 applied, the
`codex-raw-missing` and `claude-nothing-extracted` cases fail; `real-body` and
`revision-absent` still pass.
