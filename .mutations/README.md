# Mutation evidence for #1661 slice 1 (PR #2315)

Every patch mutates `slices/notify_execution_lifecycle/value_objects.py`.

| Patch | Bug it re-introduces | Test meant to kill it |
|---|---|---|
| 01-failed-maps-to-completed.patch | `WorkflowFailed` derives a `completed` notice | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice.py::test_failed_event_owes_a_failed_notice_with_its_classification` |
| 02-drop-failure-classification.patch | the failed notice drops the event's classification and reports `unclassified` instead, which still passes the validator | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice.py::test_failed_event_owes_a_failed_notice_with_its_classification` |
| 03-cancel-reason-on-any-outcome.patch | the validator lets a non-cancelled notice carry a cancel reason | `packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice.py::test_notice_fields_must_match_outcome` |

Dispatch: `just mutation-evidence 2315 "packages/syn-domain/src/syn_domain/contexts/orchestration/slices/notify_execution_lifecycle/test_execution_lifecycle_notice.py" false` (no Docker needed).
