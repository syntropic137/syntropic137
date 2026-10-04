# Repair: a read model dropped an execution's start (#1545)

## Symptom

`subscription.status` on `/api/v1/health` is `dropped_events`, with
`projection_dropped_event` in `degraded_reasons`. `subscription.unapplied_starts`
names each execution and read model:

```json
{"projection": "workflow_executions", "execution_id": "exec-db527ea0d361", "global_nonce": 39502}
```

The execution's `WorkflowExecutionStarted` is in the store, but the read model's
checkpoint went past it without applying it. Lag is zero and nothing else is
logged, so `GET /api/v1/executions/{id}` returns 404. If the execution later
failed, it may instead return a row with no `started_at` (the #598 fallback).
The read model is wrong, not slow, so waiting does not help.

The cause was the event store making a lower global nonce visible after a
higher one, so the live subscription's cursor passed the lower one
(event-sourcing-platform#337). The detector is in
`packages/syn-adapters/src/syn_adapters/subscriptions/unapplied_starts.py`. It
runs in the background every 5 minutes, and each run is a full reconciliation
from global nonce 0, so a start that commits late or a row lost after a clean
check is still found. `unapplied_starts` is null until the first run after a
restart completes.

## Repair: rebuild the two execution read models

The events are intact, so a replay restores the missing rows. The coordinator
already rebuilds a projection when its stored checkpoint version does not match
its declared version (ADR-055, "Version-based automatic rebuild"): it clears
the projection's data, deletes the checkpoint and replays from 0 on its own
track while every other projection stays live. Forcing a mismatch triggers
exactly that rebuild for these two projections and nothing else.

For exec-db527ea0d361 on the selfhost stack:

```bash
# 1. Check the start event is in the store. Expect one row at global_nonce 39502.
docker exec syn137-timescaledb psql -U syn -d syn -c \
  "SELECT global_nonce, event_type, aggregate_id
     FROM events
    WHERE tenant_id = 'syn'
      AND aggregate_id LIKE '%exec-db527ea0d361'
    ORDER BY global_nonce;"

# 2. Force a version mismatch on the two execution read models. No version is 0,
#    so the coordinator rebuilds both on the next start.
docker exec syn137-timescaledb psql -U syn -d syn -c \
  "UPDATE projection_checkpoints
      SET version = 0
    WHERE projection_name IN ('workflow_executions', 'workflow_execution_details');"

# 3. Restart the API, which runs the coordinator.
docker restart syn137-api
```

Every execution returns 404 from the list and detail endpoints until the replay
passes it. This is the same window as a release rebuild, so follow
[The projection rebuild window](../release-process.md#the-projection-rebuild-window)
and treat `catching_up` as still in progress.

Do not delete or patch the single row by hand. The detail projection derives
phases, totals and status from every event in the execution's stream, so a
hand-written row is a different wrong answer. Only a replay builds the row the
projection would have built.

## Verify

```bash
curl -s http://localhost:8137/api/v1/health \
  | jq '.subscription | {status, lagging_projections, unapplied_starts}'
# Expect: status "healthy", lagging_projections [], unapplied_starts []

curl -s http://localhost:8137/api/v1/executions/exec-db527ea0d361 \
  | jq '{execution_id, status, started_at}'
# Expect: the execution, with a non-null started_at
```

`unapplied_starts` clears without another restart, on the detector's next run
(within 5 minutes of the replay passing the start).

## If it comes back

If `dropped_events` comes back after the rebuild, the store is still committing
nonces out of order. Check that the deployed event-store image includes
event-sourcing-platform#337 (`pg_advisory_xact_lock` in `PostgresStore::append`)
before you rebuild again.
