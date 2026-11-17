# Mutation evidence: refuse remote receipts for another revision (Refs #946)

| Patch | Re-introduces | Test meant to kill it |
|---|---|---|
| `01-accept-receipt-for-another-revision.patch` | `publish_capture_receipt` records any receipt with the right storage key as a PRESENT remote replica, without comparing its original-content hash to the archived bytes (`validates_capture` not called) | `packages/syn-adapters/tests/test_capture_receipt_evidence.py::test_duplicate_acknowledgements_replay_identically_and_reject_wrong_identity`, `packages/syn-adapters/tests/test_capture_delivery_worker.py::test_receipt_publication_precedes_checkpoint_and_retries_identically[revision]` |

Local run (no Docker needed): with the patch applied, both tests fail
(`DID NOT RAISE` for the publisher; `journal.append` awaited for the worker).
