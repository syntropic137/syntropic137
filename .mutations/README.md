# SYN-1 mutation evidence (PR #1968)

Each patch re-introduces one bug. The test meant to kill it is
`packages/syn-domain/tests/integration/test_workspace_runtime_observation_persists.py`,
which needs the event store (run with docker=true).

| Patch | Bug |
|---|---|
| 01-runtime-row-drops-phase | runtime row is written without its phase id |
| 02-effective-from-requested | effective runtime is written from the requested one |
| 03-store-drops-workspace-id | the store loses the workspace id on the persisted row |

Delete `.mutations/` before merge.
