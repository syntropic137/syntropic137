# SYN-1 mutation evidence (PR #1968)

Each patch re-introduces one bug. The test meant to kill all three is

    packages/syn-domain/tests/integration/test_workspace_runtime_observation_persists.py::test_the_runtime_row_is_persisted_and_outlives_a_failed_phase

It writes to TimescaleDB through `test_infrastructure`, which uses the
`TEST_TIMESCALEDB_*` env when set and otherwise starts a pinned TimescaleDB
container itself. Dispatch with docker=true.

Baseline only, not expected to kill any patch: the Docker runtime tests, which
pull a digest-pinned busybox (`SYN_CONTRACT_TEST_IMAGE` overrides it) and fail,
never skip, when they cannot:

    packages/syn-adapters/tests/test_docker_workspace_runtime.py::test_explicit_runc_is_recorded_and_enforced
    packages/syn-adapters/tests/test_docker_workspace_runtime.py::test_auto_records_the_runtime_docker_ran

| Patch | Bug |
|---|---|
| 01-runtime-row-drops-phase | runtime row is written without its phase id |
| 02-effective-from-requested | effective runtime is written from the requested one |
| 03-store-drops-workspace-id | the store loses the workspace id on the persisted row |

Delete `.mutations/` before merge.
