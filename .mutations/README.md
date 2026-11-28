# Mutation evidence for #2396 slice 1 (PR #2398)

Postgres-backed (integration), so run with docker=true. Tests:

- `packages/syn-adapters/tests/test_capture_spool_recovery.py::test_unrecoverable_spool_is_never_claimed_again_and_keeps_its_reason`
- `packages/syn-adapters/tests/test_capture_spool_recovery.py::test_unrecoverable_mark_is_fenced_on_the_current_lease`

| Patch | Bug | Killed by |
|---|---|---|
| 01-claim-ignores-unrecoverable | `claim` drops `unrecoverable_at IS NULL` | first test: the marked spool is claimed after settlement |
| 02-mark-unrecoverable-unfenced | `mark_unrecoverable` ignores the lease token and expiry | both tests: a stale lease marks without `CaptureSpoolLeaseLost` |
| 03-reason-not-stored | the reason is written as NULL | first test: stored reason assertion |
