# 04 - Startup and Recovery: The Restart Contract

**Status:** COMPLETE

## Question

> "What exactly is the startup contract of this service?"

## Startup Sequence

From `lifecycle.py`:

1. Initialize event store connection
2. Start subscription coordinator (`_init_subscriptions`, line 347-366)
   - Creates `BackgroundWorkflowDispatcher` (live side-effect executor)
   - Wires it into `WorkflowDispatchProjection` as `execution_service`
   - Coordinator calls `_get_minimum_position()` across all 21 projections
   - Subscribes to event stream from that minimum position
   - **Catch-up replay begins** - all events from minimum position forward
3. Start events API poller (`_init_event_poller`, line 379-426)
   - Loads persisted ETag cursors from Postgres
   - Begins polling loop (30-120s interval, adaptive)
4. Start check-run poller (`_init_check_run_poller`, line 436-475)
   - Starts with empty in-memory `PendingSHAStore`
   - Begins polling loop (30-90s interval, adaptive)

## What Happens on Each Restart

| Action | Happens? | Creates new work? | Guard |
|--------|----------|------------------|-------|
| Rebuild projections from events | Yes (catch-up) | **Yes** - WorkflowDispatchProjection dispatches | Checkpoint only |
| Resume in-flight work | No | N/A | Containers are dead |
| Rescan open PRs | Yes (poller restarts) | Potentially | ETag cursor + dedup |
| Backfill missed triggers | Indirectly (catch-up) | **Yes** - if checkpoint lost | None |
| Reconcile external state | No explicit reconciliation | N/A | N/A |
| Emit new commands | **Yes** - projection dispatches during catch-up | **Yes** | **Checkpoint only** |

## The Brutal Tests

### "5 restarts in 2 minutes"

Each restart:
1. Coordinator finds minimum checkpoint across 21 projections
2. If all checkpoints are intact: catch-up replays from last position,
   WorkflowDispatchProjection skips events below its checkpoint
3. If ANY projection has a lower/missing checkpoint: subscription starts
   from that lower position. WorkflowDispatchProjection's own checkpoint
   guard at `coordinator.py:287-289` should protect it.
4. Pollers restart, load cursors from Postgres, send ETags to GitHub

**Expected result with healthy Postgres**: Zero duplicate dispatches
(checkpoint guards hold).

**Expected result with checkpoint loss**: Every historical `TriggerFired`
event replays through dispatch. With N triggers in history, N workflows
launch. **This is the bug observed in dev.**

**Expected result with Postgres unavailable**: Dedup falls to in-memory
(empty after restart), cursors unavailable (poller re-fetches all events),
guards 1-4 fall to in-memory (empty). Full blast.

### "Cold start with 200 open PRs"

1. Fresh event store (no events) + 200 open PRs on GitHub
2. Events API poller fetches up to 300 events per page from GitHub
3. Each PR event enters `EventPipeline.ingest()`
4. Fresh dedup store (no keys) - all events pass dedup
5. Each event evaluates against trigger rules
6. For each matching trigger: safety guards check
   - Guard 1 (max attempts): 0 fires recorded, passes
   - Guard 2 (cooldown): no last fire, passes
   - Guard 6 (concurrency): nothing running, passes
7. Each trigger fires, `TriggerFired` event emitted
8. WorkflowDispatchProjection processes each, calls `run_workflow()`

**Result**: Up to 200 workflow executions launch simultaneously.
Guard 7 (dispatch rate limit, 10/60s) is the only throttle, but it
only limits the evaluation side - workflows already dispatched via
the projection are not rate-limited.

**Missing**: No startup-aware throttle. No "I just started, let me
observe before acting" mode.

## The Gap: Catch-up Replay Causes Side Effects

The fundamental problem is in `coordinator.py:218-266`:

```
_get_minimum_position() -> finds lowest checkpoint across ALL projections
subscribe from that position
for each event:
    for each projection:
        if event.position > projection.checkpoint:
            projection.handle_event(event)  # SIDE EFFECT FOR DISPATCH PROJECTION
```

The coordinator treats all projections equally. It does not know that
WorkflowDispatchProjection is a process manager with side effects while
the other 20 are pure read models. There is no mechanism to say "this
projection should only process live events, not catch-up events."

## Where Startup Reconciliation Becomes Fresh Trigger Intake

**Path 1 - Projection catch-up**:
`coordinator.py:268-289` -> `projection.py:97-98` -> `run_workflow()`

Historical `TriggerFired` events are replayed through the dispatch
projection with no replay guard.

**Path 2 - Poller re-fetch**:
`github_event_poller.py` -> `pipeline.ingest()` -> `EvaluateWebhookHandler`

If ETag cursor is lost, poller re-fetches events from GitHub. If dedup
store is also fresh, events pass through to trigger evaluation as if new.

Both paths treat historical/already-handled state as fresh input.
