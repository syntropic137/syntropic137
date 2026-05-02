# Syn137 Migration Plan: ProcessManager Adoption

**Status:** DESIGN COMPLETE
**Created:** 2026-04-13
**Depends on:** ESP PR syntropic137/event-sourcing-platform#274

---

## The Bug

`WorkflowDispatchProjection` (line 98, 146-152) calls
`execution_service.run_workflow()` inside `handle_event()`. On every
restart the subscription coordinator replays historical events from the
last checkpoint. Each replayed `TriggerFired` event re-dispatches the
workflow - creating duplicate executions, burning LLM tokens, and
provisioning redundant Docker containers.

This is the **replay storm**: 50 open PRs x 20 restarts = up to 1,000
spurious workflow executions.

**Root cause:** ESP provided only `CheckpointedProjection` (designed for
pure read models). When Syn137 needed to dispatch workflows from events,
the only option was to put side effects in a projection. The framework
made the bug the path of least resistance.

**Fix:** ESP now provides `ProcessManager` (syntropic137/event-sourcing-platform#274).
Convert `WorkflowDispatchProjection` to use it.

---

## Current Architecture (Broken)

```
TriggerFired event
  |
  v
WorkflowDispatchProjection.handle_event()
  |-- writes dispatch record to projection store
  |-- calls execution_service.run_workflow()  <-- BUG: runs during replay
  |
  v
BackgroundWorkflowDispatcher.run_workflow()
  |-- creates fire-and-forget asyncio.Task
  |
  v
ExecuteWorkflowHandler.handle()
  |-- loads WorkflowTemplateAggregate
  |-- creates fresh WorkflowExecutionAggregate (no dedup check)
  |-- delegates to WorkflowExecutionProcessor.run()
```

**Problems:**
1. `run_workflow()` called during replay (no catch-up guard)
2. No idempotency check on `execution_id` before creating execution
3. `BackgroundWorkflowDispatcher` has no concurrency limit
4. `ExecuteWorkflowHandler` constructs fresh aggregate (no load-then-check)

---

## Target Architecture (ProcessManager)

```
TriggerFired event
  |
  v
WorkflowDispatchProjection.handle_event()    [PROJECTION SIDE - always runs]
  |-- writes dispatch record with status="pending"
  |-- NO side effects, replay-safe
  |
  v (coordinator gates this - live only)
WorkflowDispatchProjection.process_pending()  [PROCESSOR SIDE - live only]
  |-- reads pending dispatch records
  |-- for each pending record:
  |     |-- idempotency check (execution_id exists?)
  |     |-- dispatch via execution_service.run_workflow()
  |     |-- mark record as "dispatched" or "failed"
  |
  v
BackgroundWorkflowDispatcher.run_workflow()   [UNCHANGED]
  |-- creates asyncio.Task (with semaphore limit - Phase A2)
  |
  v
ExecuteWorkflowHandler.handle()              [+ dedup check - Phase A1]
  |-- check: does execution stream already exist?
  |-- if exists: skip (idempotent)
  |-- if new: proceed with execution
```

**Key invariant:** `process_pending()` is NEVER called during catch-up.
The coordinator checks `self._is_catching_up` and only calls
`process_pending()` for `ProcessManager` instances when live.

---

## Migration Steps

### Step 1: Update ESP submodule pointer

After syntropic137/event-sourcing-platform#274 merges, update the submodule:

```bash
cd lib/event-sourcing-platform
git fetch origin main
git checkout main
cd ../..
```

### Step 2: Convert WorkflowDispatchProjection to ProcessManager

**File:** `packages/syn-domain/.../dispatch_triggered_workflow/projection.py`

#### 2a. Change base class

```python
# Before
from event_sourcing import CheckpointedProjection, ...

class WorkflowDispatchProjection(CheckpointedProjection):
    ...

# After
from event_sourcing import ProcessManager, DispatchContext, ...

class WorkflowDispatchProjection(ProcessManager):
    ...
```

#### 2b. Split handle_event into pure projection

```python
async def handle_event(
    self,
    envelope: EventEnvelope[DomainEvent],
    checkpoint_store: ProjectionCheckpointStore,
    context: DispatchContext | None = None,
) -> ProjectionResult:
    event_type = envelope.metadata.event_type or "Unknown"
    event_data = envelope.event.model_dump()
    global_nonce = envelope.metadata.global_nonce or 0

    try:
        if event_type == "github.TriggerFired":
            await self._write_dispatch_record(event_data)  # Pure - just writes data

        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=self.PROJECTION_NAME,
                global_position=global_nonce,
                updated_at=datetime.now(UTC),
                version=self.VERSION,
            )
        )
        return ProjectionResult.SUCCESS

    except Exception:
        logger.exception("Error in dispatch projection", extra={"event_type": event_type})
        return ProjectionResult.FAILURE
```

#### 2c. Extract _write_dispatch_record (pure)

```python
async def _write_dispatch_record(self, event_data: dict[str, object]) -> None:
    """Write a pending dispatch record. No side effects."""
    workflow_id = str(event_data.get("workflow_id", ""))
    str_inputs = _to_str_dict(event_data.get("workflow_inputs", {}))
    execution_id = str(event_data.get("execution_id", ""))
    trigger_id = event_data.get("trigger_id", "")

    dispatch_record = {
        "trigger_id": trigger_id,
        "execution_id": execution_id,
        "workflow_id": workflow_id,
        "workflow_inputs": str_inputs,
        "status": "pending",              # NEW: pending until processed
        "dispatched_at": None,            # NEW: set when actually dispatched
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if self._store is not None and execution_id:
        await self._store.save(self.PROJECTION_NAME, execution_id, dispatch_record)
```

#### 2d. Implement process_pending (processor side)

```python
async def process_pending(self) -> int:
    """Dispatch pending workflows. Live-only, idempotent."""
    if self._store is None or self._execution_service is None:
        return 0

    records = await self._store.get_all(self.PROJECTION_NAME)
    pending = [r for r in records if r.get("status") == "pending"]
    processed = 0

    for record in pending:
        execution_id = str(record.get("execution_id", ""))
        workflow_id = str(record.get("workflow_id", ""))
        trigger_id = record.get("trigger_id", "")

        if not workflow_id:
            logger.warning(
                "Pending dispatch %s has no workflow_id, marking failed",
                trigger_id,
            )
            record["status"] = "failed"
            record["failure_reason"] = "no_workflow_id"
            await self._store.save(self.PROJECTION_NAME, execution_id, record)
            continue

        try:
            str_inputs = record.get("workflow_inputs", {})
            if not isinstance(str_inputs, dict):
                str_inputs = {}

            await self._execution_service.run_workflow(
                workflow_id=workflow_id,
                inputs=str_inputs,
                execution_id=execution_id,
            )

            record["status"] = "dispatched"
            record["dispatched_at"] = datetime.now(UTC).isoformat()
            await self._store.save(self.PROJECTION_NAME, execution_id, record)
            processed += 1

            logger.info(
                "Dispatched workflow %s for trigger %s -> execution %s",
                workflow_id, trigger_id, execution_id,
            )
        except Exception:
            logger.exception(
                "Failed to dispatch workflow %s for trigger %s",
                workflow_id, trigger_id,
            )
            record["status"] = "failed"
            record["failure_reason"] = "dispatch_exception"
            await self._store.save(self.PROJECTION_NAME, execution_id, record)

    return processed
```

#### 2e. Implement get_idempotency_key

```python
def get_idempotency_key(self, todo_item: dict[str, object]) -> str:
    """Dedup key is the execution_id - globally unique per dispatch."""
    return str(todo_item.get("execution_id", ""))
```

### Step 3: Update coordinator registration

**File:** `packages/syn-adapters/.../coordinator_service.py` (line 281-284)

The registration stays the same - `WorkflowDispatchProjection` is still
registered in the projection list. The coordinator detects it as a
`ProcessManager` instance via `isinstance()` and automatically gates
`process_pending()`.

No changes needed here. The coordinator's existing dispatch logic
(implemented in ESP PR #274) handles ProcessManager instances
transparently.

### Step 4: Add dispatch dedup to ExecuteWorkflowHandler (Phase A1)

**File:** `packages/syn-domain/.../execute_workflow/ExecuteWorkflowHandler.py`

Before creating the execution aggregate, check if the stream already exists:

```python
async def handle(self, command: ExecuteWorkflowCommand) -> WorkflowExecutionResult:
    # Dedup: if execution_id already has a stream, skip
    if command.execution_id:
        existing = await self._execution_repo.load(command.execution_id)
        if existing is not None:
            logger.info(
                "Execution %s already exists, skipping duplicate dispatch",
                command.execution_id,
            )
            return WorkflowExecutionResult(
                execution_id=command.execution_id,
                status="duplicate_skipped",
            )
    # ... rest of existing handle logic
```

### Step 5: Add concurrency limit to BackgroundWorkflowDispatcher (Phase A2)

**File:** `apps/syn-api/src/syn_api/_wiring.py` (line 544-600)

```python
class BackgroundWorkflowDispatcher:
    MAX_CONCURRENT = 10  # configurable

    def __init__(self, handler: ExecuteWorkflowHandler) -> None:
        self._handler = handler
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)

    async def run_workflow(self, ...) -> None:
        await self._semaphore.acquire()
        asyncio_task = asyncio.create_task(
            self._run_with_semaphore(workflow_id, inputs, execution_id, task=task),
            name=f"workflow-exec-{execution_id or workflow_id}",
        )
        self._tasks.add(asyncio_task)
        asyncio_task.add_done_callback(self._tasks.discard)

    async def _run_with_semaphore(self, ...) -> None:
        try:
            await self._run(workflow_id, inputs, execution_id, task=task)
        finally:
            self._semaphore.release()
```

---

## Verification Plan

### Test 1: Replay safety (unit)

Replay 100 TriggerFired events through the projection. Assert:
- 100 dispatch records written with `status="pending"`
- `process_pending()` never called (coordinator in catch-up mode)
- Zero calls to `execution_service.run_workflow()`

### Test 2: Live dispatch (unit)

Send 1 live TriggerFired event. Assert:
- 1 dispatch record written with `status="pending"`
- `process_pending()` called once (coordinator in live mode)
- 1 call to `execution_service.run_workflow()`
- Record updated to `status="dispatched"`

### Test 3: Idempotency (unit)

Call `process_pending()` twice for the same pending record. Assert:
- First call dispatches and marks "dispatched"
- Second call finds no pending records, returns 0

### Test 4: Restart simulation (integration)

1. Start coordinator, process 50 TriggerFired events (catch-up)
2. Transition to live
3. Send 5 new TriggerFired events
4. Assert: exactly 5 workflow dispatches (not 55)

### Test 5: 20-restart stress test (integration)

1. Create 50 TriggerFired events in event store
2. Start coordinator 20 times, each time from the same checkpoint
3. Assert: total workflow dispatches across all 20 starts = 0
   (all events are below the live boundary on each restart)
4. Send 1 new event after each restart
5. Assert: total dispatches = 20 (one per restart, for the live event)

### Test 6: Dual-path dedup (integration)

1. Dispatch same `execution_id` twice via `ExecuteWorkflowHandler`
2. Assert: first succeeds, second returns `duplicate_skipped`

---

## Files Changed

| File | Change | Phase |
|------|--------|-------|
| `packages/syn-domain/.../dispatch_triggered_workflow/projection.py` | Convert to ProcessManager | B1 |
| `packages/syn-domain/.../execute_workflow/ExecuteWorkflowHandler.py` | Add execution_id dedup | A1 |
| `apps/syn-api/src/syn_api/_wiring.py` | Add semaphore to BackgroundWorkflowDispatcher | A2 |
| `apps/syn-api/src/syn_api/routes/executions/commands.py` | Wrap background task exceptions | A3 |
| `packages/syn-domain/.../aggregate_trigger/TriggerRuleAggregate.py` | Call can_fire() in record_fired() | B3 |
| `packages/syn-adapters/.../coordinator_service.py` | No changes needed (ProcessManager auto-detected) | -- |
| `lib/event-sourcing-platform/` | Update submodule pointer | Pre-req |

---

## Migration Safety

**Backwards compatibility:** The projection store already has dispatch
records from the current implementation. After migration:

- Existing records have no `status` field. `process_pending()` filters
  on `status == "pending"`, so old records without a status field are
  ignored (they were already dispatched by the old code).
- New records get `status="pending"` and are processed normally.
- No data migration needed.

**Rollback:** If something goes wrong, revert the projection.py change.
The coordinator treats `CheckpointedProjection` and `ProcessManager`
identically for `handle_event()` - the only difference is whether
`process_pending()` is called. Reverting removes the ProcessManager
behavior and restores the old (buggy but functional) behavior.

**Checkpoint continuity:** The projection name (`WORKFLOW_DISPATCH`) and
version (1) are unchanged. The coordinator picks up from the last
checkpoint. No re-replay of the entire event store.

---

## What This Does NOT Fix

These require separate phases (C, D, E in PROJECT-PLAN.md):

1. **Cost gates** - SpendTracker not wired into dispatch path
2. **Per-repo rate limits** - no rate limit on workflow executions per repo
3. **ExpectedVersion.NoStream** - execution streams don't enforce uniqueness at store level
4. **Distributed locks** - _fire_locks are in-memory asyncio.Lock (single-instance only)
5. **Events API pagination** - only fetches first page (30 events)
6. **Dedup TTL mismatch** - settings say 24h, adapter defaults to 7d
7. **Pending SHA persistence** - in-memory, lost on restart
