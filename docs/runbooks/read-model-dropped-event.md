# Runbook: an execution's start is in the store but not in the read models

**Symptom.** `/health` carries a warning beginning `N execution(s) have a
WorkflowExecutionStarted event in the store that the execution read models never
applied`, and the API logs `Read model drift (#1545)` at ERROR. A running execution
404s on `GET /api/v1/executions/{id}`, or a finished one shows `started_at: null`,
no `workflow_name` and 0 phases.

**Cause (#1545).** Before the event store's commit-order fix, a live subscriber
could skip an event whose append committed after an append holding a higher global
nonce. The event is in the store; the projections passed it. Nothing errors and
the checkpoints are at the head, so this check (`syn_api/services/unprojected_executions.py`)
is the only signal.

## Repair

The two execution projections are rebuilt from the store. Their handlers are
upserts keyed by execution id and the rebuild clears their tables first, so a
rebuild leaves every other execution exactly as it was. Other projections are not
touched and keep serving live events while it runs (ADR-055, #1318).

1. Confirm the event is in the store (exec-db527ea0d361 is the #1545 case):

   ```bash
   docker exec syn137-timescaledb psql -U syn -d syn -c \
     "SELECT global_nonce, event_type FROM events
       WHERE tenant_id = 'syn' AND aggregate_id LIKE '%exec-db527ea0d361%'
       ORDER BY global_nonce;"
   ```

   Expect `WorkflowExecutionStarted` at 39502. If it is absent, this runbook does
   not apply: the read models are right and the store is not.

2. Force a rebuild of both execution projections by making their stored version
   disagree with the declared one. On the next start the coordinator clears their
   data and checkpoints and replays them from 0
   (`coordinator.py`, "Projection version mismatch, clearing data and checkpoint for rebuild"):

   ```bash
   docker exec syn137-timescaledb psql -U syn -d syn -c \
     "UPDATE projection_checkpoints SET version = 0
       WHERE projection_name IN ('workflow_executions', 'workflow_execution_details');"
   docker restart syn137-api
   ```

3. Wait until `/health` no longer reports `subscription.is_catching_up`, then check:

   ```bash
   curl -s localhost:8137/api/v1/executions/exec-db527ea0d361 | jq '{started_at, workflow_name, total_phases, status}'
   ```

   `started_at` and `workflow_name` must be set. The drift warning clears on the
   watcher's next pass (every 5 minutes).

Container names and the port are the self-host defaults; substitute yours.
While the rebuild runs, the execution list and detail endpoints may 404 recent
executions. That is the documented rebuild window, not a new drop.
