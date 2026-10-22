# Mutation evidence for #1952

| Patch | Bug it re-introduces | Test meant to kill it |
|---|---|---|
| `01-backfill-batch-share-locks-agent-events.patch` | Each backfill batch takes `LOCK TABLE agent_events IN SHARE MODE`, which conflicts with every INSERT's RowExclusiveLock, for the whole batch | `packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_usage_rollup_backfill_does_not_block_ingest.py::test_inserts_flow_during_the_backfill_and_each_is_counted_once` |

Run with `docker=true` (TimescaleDB). Killed by the held-lock check in
`_commits_while_parked` (the parked backfill holds ShareLock on agent_events),
and failing that by the writer queuing behind the backfill's pid.
