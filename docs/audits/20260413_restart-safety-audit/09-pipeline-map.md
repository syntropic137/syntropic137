# 09 - Trigger Pipeline: Current vs Ideal

**Status:** COMPLETE

## Current Pipeline

```
GitHub (webhooks, Events API, Checks API)
  |
  |  [OBSERVE - clean]
  v
Webhook Endpoint / Events API Poller / Check-Run Poller
  |  Normalize to NormalizedEvent
  v
EventPipeline.ingest()                      -- dedup check (Postgres, fail-open)
  |
  |  [DECIDE - mostly clean]
  v
EvaluateWebhookHandler.evaluate()
  |  Condition matching
  |  Safety guards 1-7 (mix of durable + in-memory)
  |  Per-(trigger, PR) asyncio.Lock
  v
EvaluateWebhookHandler._fire_trigger()      -- BOUNDARY BLUR: decide + execute
  |  Load TriggerRuleAggregate
  |  RecordTriggerFiredCommand (aggregate has zero guards)
  |  Save aggregate -> TriggerFiredEvent emitted
  |  record_fire() in query store
  v
TriggerFiredEvent -> Event Store
  |
  |  [EXECUTE - broken boundary]
  v
SubscriptionCoordinator (catch-up replay)
  |  Replays from minimum checkpoint across 21 projections
  v
WorkflowDispatchProjection.handle_event()   -- VIOLATION: projection with side effects
  |  Writes dispatch record (observe - ok)
  |  Calls run_workflow() (execute - NOT ok)
  v
BackgroundWorkflowDispatcher.run_workflow()  -- NO DEDUP, fire-and-forget
  |  Creates asyncio.Task (unbounded)
  v
ExecuteWorkflowHandler.handle()             -- Only checks: workflow exists
  |  No budget check, no idempotency
  v
WorkflowExecutionProcessor.run()            -- Creates new aggregate (no ExpectedVersion)
  |  No cost gate
  v
WorkspaceProvisionHandler                   -- Docker container created
  v
AgentExecutionHandler                       -- LLM called, MONEY SPENT
```

### Current file mapping

| Pipeline stage | File(s) | Concern | Clean? |
|---------------|---------|---------|--------|
| Fact discovery | `github_event_poller.py`, `check_run_poller.py`, webhook route | Observe | Clean |
| Normalization | `normalized_event.py`, `dedup_keys.py` | Observe | Clean |
| Dedup | `pipeline.py`, `postgres_dedup.py` | Observe | Clean (fail-open noted) |
| Trigger evaluation | `EvaluateWebhookHandler.py`, `safety_guards.py`, `condition_evaluator.py` | Decide | Mostly clean |
| Command issuance | `EvaluateWebhookHandler._fire_trigger()` + `TriggerRuleAggregate.record_fired()` | Decide + Execute | **Violation** (aggregate has no guards) |
| Workflow dispatch | `dispatch_triggered_workflow/projection.py` | **Execute disguised as Observe** | **Critical violation** |
| Workflow execution | `BackgroundWorkflowDispatcher`, `ExecuteWorkflowHandler`, `WorkflowExecutionProcessor` | Execute | Clean but unguarded |

## Ideal Pipeline

```
GitHub (webhooks, Events API, Checks API)
  |
  |  [OBSERVE]
  v
Webhook Endpoint / Events API Poller / Check-Run Poller
  |  Normalize to NormalizedEvent
  v
EventPipeline.ingest()                      -- dedup check (Postgres, fail-open)
  |
  |  [DECIDE]
  v
EvaluateWebhookHandler.evaluate()
  |  Condition matching
  |  Safety guards (all durable)
  v
TriggerRuleAggregate.record_fired()         -- AGGREGATE ENFORCES can_fire()
  |  Guards: status == ACTIVE, not at max_attempts, not in cooldown
  |  Emits TriggerFiredEvent
  v
TriggerFiredEvent -> Event Store
  |
  |  [OBSERVE - pure projection]
  v
WorkflowDispatchProjection.handle_event()
  |  Writes dispatch record: { execution_id, workflow_id, status: "pending" }
  |  NO side effects. Replay-safe.
  |  Checkpoint saved AFTER record write.
  v
  |  [DECIDE - processor reads to-do list]
  v
WorkflowDispatchProcessor                   -- NEW COMPONENT
  |  Reads dispatch records with status "pending"
  |  For each pending record:
  |    Check: does execution_id already exist? (idempotency)
  |    Check: is there budget? (SpendTracker)
  |    Check: is per-repo rate limit ok? (durable counter)
  |    If all pass: dispatch
  |    Mark record: "dispatched" (atomic with dispatch)
  |    On failure: mark record: "failed"
  v
  |  [EXECUTE - guarded]
  v
ExecuteWorkflowHandler.handle()
  |  ExpectedVersion.NoStream on execution stream
  |  Budget allocation (SpendTracker)
  v
WorkflowExecutionProcessor.run()
  |  Concurrent task pool (bounded)
  v
WorkspaceProvisionHandler                   -- Docker container created
  v
AgentExecutionHandler                       -- LLM called, money spent
  v
TriggerDispatchCompleted/Failed event       -- CLOSES THE LIFECYCLE LOOP
  |  Back to TriggerRuleAggregate
  v
Trigger fire state: pending -> dispatched -> completed/failed
```

### Key differences

| Aspect | Current | Ideal |
|--------|---------|-------|
| Projection behavior | Dispatches workflows (side effect) | Writes dispatch records only (pure) |
| Dispatch decision | Implicit in projection (every TriggerFired = dispatch) | Explicit in Processor (checks to-do list) |
| Replay safety | Broken (projection re-dispatches on replay) | Safe (projection only writes records, Processor checks idempotency) |
| Aggregate guards | None (record_fired is a dumb emitter) | Enforces can_fire(), status, max_attempts |
| Cost gate | None (zero checks before spend) | SpendTracker + per-repo rate limit + budget allocation |
| Dispatch idempotency | None | execution_id check before launch + ExpectedVersion.NoStream |
| Task concurrency | Unbounded asyncio tasks | Bounded task pool |
| Trigger lifecycle | Implicit, scattered | Explicit state machine with domain events |
| Checkpoint gap | Dispatch before checkpoint = crash = re-dispatch | Record write before checkpoint = crash = re-write (idempotent) |

## Gap Analysis

| # | Gap | Current state | Ideal state | Fix ref |
|---|-----|--------------|-------------|---------|
| 1 | Projection has side effects | `projection.py:148` calls `run_workflow()` | Projection writes records only | C1 |
| 2 | No dispatch processor | Projection IS the dispatcher | Separate Processor reads to-do list | C2 |
| 3 | No dispatch idempotency | Every TriggerFired = new dispatch | Check execution_id before launch | C3 |
| 4 | Aggregate has no guards | `record_fired()` is unconditional | Enforce `can_fire()` | H3 |
| 5 | No cost gate before spend | 6-step chain, zero checks | SpendTracker at Processor + Handler | H1 |
| 6 | No replay-mode detection | Catch-up and live share same path | Coordinator signals replay mode | H2 |
| 7 | Unbounded concurrent tasks | `_tasks` is unbounded set | Bounded semaphore or pool | H4 |
| 8 | No per-repo rate limit | Global only (10/60s, in-memory) | Per-repo, durable, Postgres-backed | M1 |
| 9 | No stream-level dedup | New aggregate each dispatch | ExpectedVersion.NoStream | M2 |
| 10 | No trigger lifecycle closure | Fire event only, no completion | Completed/Failed events back to aggregate | M3 |

## The Processor To-Do List Pattern (from AGENTS.md)

This is not a new invention. The project's own AGENTS.md specifies this
pattern for long-running processes:

> - **Aggregate** handles commands and emits events, enforces rules
> - **To-Do List Projection** builds a list of pending work from events
> - **Processor** reads the to-do list and dispatches commands - zero
>   business logic
> - **Infrastructure Handlers** react to commands, do async work, emit
>   result events

The WorkflowDispatchProjection is currently doing the Projection AND the
Processor AND the Infrastructure Handler in one component. Splitting it
into three is the structural fix.
