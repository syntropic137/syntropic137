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

## Fix round 1 (verify B2, B3, B4)

The fix changed `SpoolRecoveryPort.open` to take the lease and a fence, so
02 and 03 above no longer apply to the source. They are left untouched; 05 and
06 are the same bugs rebased onto the new source. Each was killed locally by
the unit gate.

| Patch | Bug | Killing test |
|---|---|---|
| 05-upload-failure-releases-sandbox-rebased | 02, rebased | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_failed_archive_keeps_sandbox_paused_and_spool_retryable` |
| 06-docker-port-for-remote-row-rebased | 03, rebased | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_worker_routes_remote_row_to_remote_port_and_claims_only_reachable_backends` |
| 07-unsettled-sandbox-writer-stopped | recovery resumes and stops the writer of a spool with no terminal fact | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_unsettled_spool_never_reaches_a_healthy_writer` |
| 08-stale-lease-stops-writer-after-slow-attach | no fence after attach, so a worker whose lease expired during attach stops the writer | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_lease_lost_during_a_slow_attach_stops_nothing` |
| 09-removal-kills-live-writer | retention removal kills a sandbox whose agent still runs | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_removal_refuses_a_sandbox_whose_writer_still_runs` |
| 10-missing-executor-accepted | a remote row without `executor_id` validates | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_remote_spool_row_must_name_its_sandbox_and_executor[executor_id]` |

```
just mutation-evidence 2078 "packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_live_writer_is_stopped_drained_and_killed_only_after_mark_drained packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_failed_archive_keeps_sandbox_paused_and_spool_retryable packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_worker_routes_remote_row_to_remote_port_and_claims_only_reachable_backends packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_open_stops_writer_before_reading_and_pauses_on_exit packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_unsettled_spool_never_reaches_a_healthy_writer packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_lease_lost_during_a_slow_attach_stops_nothing packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_removal_refuses_a_sandbox_whose_writer_still_runs packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_remote_spool_row_must_name_its_sandbox_and_executor[executor_id]" false
```

## Fix round 2 (reverify B3)

`RecoverySandboxes.attach` became `resume` plus `pause`, so the closing pause
is decided from lease authority. 05 and 08 no longer apply to that source; they
are left untouched and 12 and 13 are the same bugs rebased. Each patch was
applied, the unit module run, and the patch reversed.

| Patch | Bug | Killing test |
|---|---|---|
| 11-stale-worker-pauses-new-owners-sandbox | a worker whose lease was lost during attach still pauses the sandbox the new owner is reading | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_lease_lost_during_a_slow_attach_stops_nothing` |
| 12-upload-failure-releases-sandbox-rebased-2 | 05, rebased | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_failed_archive_keeps_sandbox_paused_and_spool_retryable` |
| 13-stale-lease-stops-writer-after-slow-attach-rebased | 08, rebased | `packages/syn-adapters/tests/test_sandbox_spool_recovery.py::test_lease_lost_during_a_slow_attach_stops_nothing` |

The command in the previous section already names every killing test.
