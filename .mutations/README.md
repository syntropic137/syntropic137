# Mutation evidence for #1916 (PR #2078)

Each patch re-introduces one bug in production source. All four were killed
locally (unit gate, no Docker); run them on the trusted runner with
`docker=false`:

```
just mutation-evidence 2078 "packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_live_writer_is_stopped_drained_and_killed_only_after_mark_drained packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_failed_archive_keeps_sandbox_paused_and_spool_retryable packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_worker_routes_remote_row_to_remote_port_and_claims_only_reachable_backends packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_open_stops_writer_before_reading_and_pauses_on_exit" false
```

| Patch | Bug | Killing test |
|---|---|---|
| 01-release-before-mark-drained | worker releases (kills the sandbox) before `mark_drained` | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_live_writer_is_stopped_drained_and_killed_only_after_mark_drained` |
| 02-upload-failure-releases-sandbox | a failed archive upload kills the sandbox instead of leaving it paused | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_failed_archive_keeps_sandbox_paused_and_spool_retryable` |
| 03-docker-port-for-remote-row | recovery opens an E2B row with the Docker port | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_worker_routes_remote_row_to_remote_port_and_claims_only_reachable_backends` |
| 04-post-drain-write-accepted | `exclusive` set from the run state (fencing) without stop-and-confirm, so the live agent writes after the drain | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_live_writer_is_stopped_drained_and_killed_only_after_mark_drained` (also `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_open_stops_writer_before_reading_and_pauses_on_exit`) |

The Postgres-backed integration tests in the same module
(`test_fresh_worker_drains_live_writer_under_fencing_and_kills_only_after_drain`,
`test_failed_archive_upload_leaves_sandbox_paused_and_spool_retryable`) should
also kill 01, 02 and 04, but they did not run in the authoring workspace (no
Postgres there).
