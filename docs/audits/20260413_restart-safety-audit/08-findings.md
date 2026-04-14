# 08 - Findings and Fix Plan

**Status:** COMPLETE

## Invariant Scorecard

| # | Invariant | Status | Evidence |
|---|-----------|--------|----------|
| 1 | Trigger has stable content-based dedup key | **PROVEN** | `dedup_keys.py` uses PR number, SHA, check_run ID - same key from webhook and polling |
| 2 | No launch without atomic dedup key recording | **DISPROVEN** | `WorkflowDispatchProjection` calls `run_workflow()` with zero dedup. `BackgroundWorkflowDispatcher` has no idempotency check. |
| 3 | Startup reconciliation cannot issue unseen-unproven work | **DISPROVEN** | Coordinator catch-up replays TriggerFired through dispatch projection. If checkpoint lost, all history re-fires. |
| 4 | Projection rebuild is side-effect free | **DISPROVEN** | `WorkflowDispatchProjection` dispatches real workflows during replay. No replay-vs-live flag exists. |
| 5 | Polling and webhooks converge on same trigger identity | **PROVEN** | All sources produce `NormalizedEvent` with identical content-based dedup keys, converge at `EventPipeline.ingest()`. |
| 6 | At most one active workflow per logical unit of work | **DISPROVEN** | No enforcement at dispatch boundary. Guard 6 (concurrency) is in-memory only, lost on restart. No `ExpectedVersion.NoStream`. |
| 7 | Expensive actions guarded at last responsible moment | **DISPROVEN** | Zero cost gates in dispatch chain. SpendTracker exists but is not wired. No budget ceiling. |

**Score: 2/7 proven, 5/7 disproven.** The observe/decide boundary is
clean. The decide/execute boundary is broken.

## Three-Way Split Violations

| Component | Violation | Severity | Fix |
|-----------|----------|----------|-----|
| WorkflowDispatchProjection | Observe + Execute (dispatches during replay) | **Critical** | Extract to Processor To-Do List |
| EvaluateWebhookHandler._fire_trigger | Decide + Execute (evaluates + records + fires) | Medium | Move invariants to aggregate |
| TriggerRuleAggregate.record_fired | No guards (should Decide, actually just Records) | Medium | Enforce `can_fire()` in `record_fired` |
| BackgroundWorkflowDispatcher | Execute with no dedup | **High** | Add execution_id idempotency check |
| Dispatch chain (6 steps) | Execute with zero cost gates | **Critical** | Wire SpendTracker before container creation |

## Stress Scenario: 20 Restarts in 1 Hour, 50 Open PRs

### Restart 1 (cold start, fresh DB)

1. Coordinator starts, finds no checkpoints for any projection
2. Subscribes from position 0 (full event replay)
3. WorkflowDispatchProjection receives every historical TriggerFired
4. Each TriggerFired calls `run_workflow()` unconditionally
5. If there are 200 historical trigger fires: **200 workflows launch
   simultaneously as unbounded asyncio tasks**
6. Events API poller starts, fetches 30 events per repo, all pass
   empty dedup, trigger evaluation begins for live events too
7. Guard 7 (rate limit, 10/60s) provides some throttling on the
   evaluation side but NOT on the replay-dispatch side

**Cost**: 200+ workflow executions. Each burns LLM tokens + container
compute. No budget ceiling.

### Restart 2 (warm DB, checkpoints intact)

1. Coordinator loads checkpoints from Postgres
2. WorkflowDispatchProjection resumes from its saved position
3. Only events after the checkpoint are processed
4. Events API poller loads ETag cursor, sends conditional request
5. **Zero duplicate dispatches** (checkpoint guard holds)

**Cost**: Zero spurious executions. This is the healthy path.

### Restart 3 (warm DB, but crash happened between dispatch and checkpoint save)

1. Coordinator loads checkpoints
2. WorkflowDispatchProjection processes events from last checkpoint
3. The TriggerFired event that was dispatched-but-not-checkpointed
   replays through `_on_trigger_fired()` again
4. **One duplicate workflow launches**

**Cost**: 1 spurious execution per crash-between-dispatch-and-checkpoint.

### Restart 4 (projection version bumped in code deploy)

1. Coordinator detects version mismatch for WorkflowDispatchProjection
2. Clears its checkpoint and data
3. Projection replays from position 0
4. **All historical TriggerFired events re-dispatch**

**Cost**: Same as Restart 1. Full replay storm.

### Summary: 20 restarts with 50 open PRs

| Scenario | Frequency | Spurious executions |
|----------|-----------|-------------------|
| Checkpoints intact | Most restarts | 0 |
| Checkpoint loss (DB reset) | Occasional (dev, selfhost) | ALL historical triggers |
| Crash between dispatch+checkpoint | Occasional | 1 per occurrence |
| Projection version bump | Each code deploy | ALL historical triggers |
| Poller re-fetch (cursor lost) | If Postgres down | Up to 30 events per repo |

**Worst case in 1 hour**: If checkpoints are lost on every restart,
20 restarts x (all historical triggers) = unbounded. With 200 historical
triggers: potentially 4000 workflow launches.

**Likely case**: Most restarts have intact checkpoints. 1-2 restarts
with issues could produce 200-400 spurious executions.

## Prioritized Fix Plan

### Critical (P0) - Blocks safe operation

| # | Fix | Files to change | Layer | Effort |
|---|-----|----------------|-------|--------|
| C1 | **Make WorkflowDispatchProjection pure** - write dispatch records only, no `run_workflow()` call | `dispatch_triggered_workflow/projection.py` | Domain | Medium |
| C2 | **Add WorkflowDispatchProcessor** - reads dispatch to-do list, fires workflows with idempotency check on execution_id | New file in `dispatch_triggered_workflow/` | Application | Medium |
| C3 | **Add dispatch idempotency** - check if execution_id already exists before creating aggregate | `BackgroundWorkflowDispatcher` or `ExecuteWorkflowHandler` | Application | Small |

**C1+C2 together implement the Processor To-Do List pattern** already
specified in AGENTS.md. The projection writes `pending` dispatch records.
The processor reads them, dispatches, marks `dispatched`. On restart, the
processor checks which records are `pending` vs `dispatched` and only
processes pending ones. Replay-safe by construction.

**C3 is the quick mitigation** while C1+C2 are built. Before calling
`ExecuteWorkflowHandler.handle()`, check if an execution with this
`execution_id` already exists in the repository. If it does, skip.

### High (P1) - Prevents cost leakage

| # | Fix | Files to change | Layer | Effort |
|---|-----|----------------|-------|--------|
| H1 | **Wire SpendTracker** into execution path - budget check before container creation | `WorkflowExecutionProcessor`, `WorkspaceProvisionHandler` | Application | Medium |
| H2 | **Add replay-mode flag** to subscription coordinator - projections know if they're in catch-up | `coordinator.py`, `CheckpointedProjection` interface | Infrastructure (ESP) | Medium |
| H3 | **Move trigger invariants to aggregate** - `record_fired` must call `can_fire()` | `TriggerRuleAggregate.py` | Domain | Small |
| H4 | **Add concurrent task pool limit** to BackgroundWorkflowDispatcher | `_wiring.py` | Infrastructure | Small |

### Medium (P2) - Architectural clarity

| # | Fix | Files to change | Layer | Effort |
|---|-----|----------------|-------|--------|
| M1 | **Add per-repo durable rate limit** - max N workflows per repo per hour | `safety_guards.py`, new Postgres-backed counter | Domain | Medium |
| M2 | **Add ExpectedVersion.NoStream** on execution stream creation | `WorkflowExecutionProcessor` | Infrastructure | Small |
| M3 | **Add trigger-fire lifecycle events** - TriggerDispatchCompleted/Failed | `TriggerRuleAggregate`, new events | Domain | Medium |
| M4 | **Enable cross-trigger cooldown** (currently disabled, = 0) | Configuration only | Domain | Trivial |

### Low (P3) - Hygiene

| # | Fix | Files to change | Layer | Effort |
|---|-----|----------------|-------|--------|
| L1 | **Implement Events API pagination** | `events_api_client.py` | Infrastructure | Small |
| L2 | **Fix dedup TTL mismatch** (settings 24h vs adapter 7d) | `polling.py`, `postgres_dedup.py` | Infrastructure | Trivial |
| L3 | **Persist pending SHAs** for check-run poller | `pending_sha_store.py`, new Postgres adapter | Infrastructure | Small |
| L4 | **Prune _fire_locks dict** (unbounded growth) | `EvaluateWebhookHandler.py` | Application | Trivial |
| L5 | **Remove dead last_event_id** (stored but never read) | `events_api_client.py` | Infrastructure | Trivial |

## Execution Order

```
Phase A: Stop the bleeding (1-2 days)
  C3 (dispatch idempotency check - quick mitigation)
  H4 (task pool limit - prevents resource exhaustion)

Phase B: Structural fix (3-5 days)
  C1 + C2 (Processor To-Do List pattern)
  H3 (aggregate invariants)

Phase C: Cost safety (2-3 days)
  H1 (wire SpendTracker)
  M1 (per-repo rate limit)
  M2 (ExpectedVersion.NoStream)

Phase D: Observability and polish (2-3 days)
  H2 (replay-mode flag in coordinator)
  M3 (trigger lifecycle events)
  M4 (enable cross-trigger cooldown)

Phase E: Hygiene (1-2 days)
  L1-L5 (pagination, TTL fix, SHA persistence, cleanup)
```

## Additional Findings (Beyond Trigger Pipeline)

### Critical: Silent failures / ghost executions

- `ListSessionsProjection.mark_orphaned_as_failed()` has `except Exception: pass`
  (line 320-321) - data corruption, orphaned sessions never cleaned up
- `execute_workflow_endpoint()` background task does not wrap exceptions -
  if `execute()` raises (not returns Err), the task dies silently. API
  returns success but execution never happens. Ghost execution.
- `WorkflowDispatchProjection.handle_event()` - dispatch failure re-raises
  (line 161), so checkpoint does NOT advance on failure. However, the
  coordinator retries the event on next subscription tick, and if the
  failure is permanent (bad workflow_id), it retries forever with no
  dead-letter mechanism.

### Critical: In-memory locks for correctness

- `_fire_locks` (asyncio.Lock dict) in `EvaluateWebhookHandler` is used
  to prevent race conditions between concurrent guard checks and fire
  recording. This is **in-memory only**. Breaks on restart (concurrent
  handlers race) and breaks on multi-instance deployment (separate lock
  dicts per instance = no mutual exclusion).

### High: God services

- `LifecycleService` (588 lines) - lifecycle, degradation, recovery, credentials
- `WorkflowExecutionProcessor` (710 lines) - orchestration, error handling, observability
- `EventStreamProcessor` (588 lines) - streaming, metrics, state transitions

These accumulate responsibilities and make state machine bugs invisible
because exceptions are swallowed at multiple levels.

### Medium: Debouncer state loss

- `TriggerDebouncer._pending` stores deferred trigger tasks in memory.
  Lost on restart = deferred triggers never fire. No formal shutdown hook.

### Clean: Bounded context independence

- No circular dependencies between bounded contexts. This is healthy.
- Async task tracking is generally well-done (BackgroundWorkflowDispatcher,
  LifecycleService, EventPipeline all track tasks properly).

## The Anchor Answer

> "What durable fact proves this workflow has already been considered
> for this exact trigger?"

**Current answer**: Nothing. There is no durable record linking a trigger
fire to a dispatched workflow that is checked at the point of dispatch.

**After fix (C1+C2)**: The dispatch record in the projection store with
status `dispatched` and the matching `execution_id`. The Processor checks
this record before dispatching. The record survives restart. Replay
rebuilds the records but the Processor only acts on `pending` ones.
