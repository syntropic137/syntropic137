# Mutation evidence: ADR-079 slice 2 (#2383)

Each patch re-introduces one bug into `packages/syn-adapters/src/syn_adapters/events/schema.py`.
All the tests that kill them need TimescaleDB, so dispatch with Docker (the default):

```
just mutation-evidence <PR> "packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_canonical_totals_rollup_parity.py::test_reported_observations_are_the_non_zero_turns_per_key packages/syn-domain/tests/contexts/agent_sessions/slices/canonical_totals/test_usage_rollup_backfill_does_not_block_ingest.py"
```

| Patch | Bug | Killed by |
|---|---|---|
| `01-count-zero-token-turns-as-reported.patch` | the trigger counts every turn as reported, including zero-token ones | parity `test_reported_observations_are_the_non_zero_turns_per_key` (zero-token turns in batches B2 and E); backfill-does-not-block (the writer's zero-token turns) |
| `02-drop-widened-keep-condition.patch` | the backfill keeps a key only where observations are owed, so keys the pre-column trigger wrote never get their reported count | parity `test_reported_observations_are_the_non_zero_turns_per_key` (batch B, upgraded from 007's trigger; also `owed_only > 0`) |
| `03-count-turn-in-backfill-and-trigger.patch` | the backfill does not subtract the trigger's reported count, so a turn is counted by both | parity (turns on A's keys through the new trigger, then D's reconcile); backfill-does-not-block (the writer on keys the backfill visits) |
