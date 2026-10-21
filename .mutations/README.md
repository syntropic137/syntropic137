# Mutation evidence for #1952

Both patches must be killed by
`packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_usage_rollup_backfill_does_not_block_ingest.py::test_inserts_flow_during_the_backfill_and_each_is_counted_once`
(Docker-backed: run with `docker=true`).

| Patch | Bug it re-introduces |
|---|---|
| 01-backfill-holds-agent-events-across-all-batches | The pre-#1558-r2 shape: one transaction over every batch, holding `AGENT_EVENTS_TRIGGER_DDL_LOCK_SQL`. Holding the transaction alone would not block inserts (the backfill otherwise takes only an advisory lock), so the patch takes the table lock too. |
| 02-each-backfill-batch-locks-agent-events | Each batch takes `SHARE` on agent_events, which conflicts with INSERT, for the length of that batch only. |

Under either, the writer's backend is queued on a relation lock while the
backfill is parked mid-batch, and `_commits_while_parked` fails on it.
