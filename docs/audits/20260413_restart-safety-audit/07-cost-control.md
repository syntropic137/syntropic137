# 07 - Cost Control: Gates Before Spend

**Status:** COMPLETE

## Question

> "What are the top 5 code paths where duplicate or accidental workflow
> execution can burn user money?"

## Top 5 Dangerous Code Paths

### 1. Projection replay storm (CRITICAL)

**Path**: Service restart -> coordinator catch-up -> WorkflowDispatchProjection
replays all historical TriggerFired events -> each calls `run_workflow()`

**Last gate**: Projection checkpoint (position check at `coordinator.py:287-289`)

**Sufficient?**: **No.** If checkpoint is lost (DB recreated, version bump,
corruption), every historical TriggerFired event dispatches a real workflow.
With H historical events, H workflows launch simultaneously. No upper bound.

### 2. Cold start with many open PRs (HIGH)

**Path**: Fresh start -> Events API poller fetches up to 30 events per repo
-> all pass empty dedup -> all evaluate against triggers -> all fire

**Last gate**: Guard 7 dispatch rate limit (10/60s, in-memory)

**Sufficient?**: **No.** Guard 7 limits the evaluation side. Workflows
already dispatched via the projection are not rate-limited. Also, Guard 7
resets on restart.

### 3. Fail-open dedup during infrastructure outage (HIGH)

**Path**: Postgres/Redis unavailable -> dedup check throws -> fail-open
processes event -> trigger fires -> workflow launches

**Last gate**: Safety guards 1-4 (but these also need Postgres for the
persistent variant)

**Sufficient?**: **No.** If Postgres is down, both dedup and safety guards
fall to in-memory variants. After a restart, everything is empty.

### 4. Concurrent webhook + poll for same event (MEDIUM)

**Path**: Same event arrives via webhook AND polling within the dedup
window -> both pass dedup simultaneously before either records -> both
fire triggers

**Last gate**: Per-(trigger, PR) asyncio.Lock + Guard 6 concurrency

**Sufficient?**: **Mostly.** The asyncio.Lock serializes in-process. But
if the process restarts between the two deliveries, the lock is lost and
Guard 6 (in-memory) is reset. Postgres-backed guards 1-4 provide backup.

### 5. Dedup key expiry after 7 days (LOW)

**Path**: Event processed 8 days ago -> dedup key expired -> same event
re-observed (poller re-fetch after downtime) -> passes dedup as "new"

**Last gate**: Safety guards (max_attempts, daily_limit, cooldown)

**Sufficient?**: **Partially.** Daily limits reset each day. Max attempts
is cumulative but requires the persistent store to be intact.

## SpendTracker: Exists But Not Wired

**`syn-tokens/src/syn_tokens/spend.py`** has a full budget allocation,
check, and enforcement API.

**It is called nowhere in the live execution path.** Zero references in
`syn-api` or `syn-domain`. Only used in `scripts/e2e_github_app_test.py`.

This is the most direct missing guard. The system has the capability to
check budgets before spend but does not use it.

## The Dispatch Chain: Zero Cost Gates

Tracing from trigger fire to LLM invocation:

```
1. WorkflowDispatchProjection.handle_event()     -- no guard
2. BackgroundWorkflowDispatcher.run_workflow()    -- no guard, no dedup
3. ExecuteWorkflowHandler.handle()                -- workflow must exist (only check)
4. WorkflowExecutionProcessor.run()               -- no budget check
5. WorkspaceProvisionHandler.handle()             -- no cost gate
6. AgentExecutionHandler.handle()                 -- no budget check
                                                     (money spent here)
```

**There is no cost gate anywhere in this chain.** The only check is
"does the workflow template exist?" at step 3.

## No ExpectedVersion Guard

`WorkflowExecutionAggregate.start_execution()` checks `self.id is not None`
but this is per-instance. Each dispatch creates a new aggregate instance.
The event store does not use `ExpectedVersion.NoStream` on execution
streams, so the same execution_id could theoretically create duplicate
streams.

## Unbounded Concurrent Tasks

`BackgroundWorkflowDispatcher._tasks` is an unbounded `set()` of asyncio
tasks (`_wiring.py:554`). There is no pool limit. A replay storm creates
as many concurrent tasks as there are historical TriggerFired events.

## Theoretical Maximum (All Guards Failed)

**After a restart with checkpoint loss**: Every historical TriggerFired
event in the event store fires simultaneously. If there are 1000 historical
triggers, 1000 workflows launch as concurrent asyncio tasks.

**Steady-state with rate limiter warm**: 600 dispatches/hour globally
(Guard 7: 10/60s). No per-repo cap - one noisy repo can consume the
entire budget.

## Missing Guards (Prioritized)

| # | Missing guard | Impact | Fix layer |
|---|--------------|--------|-----------|
| 1 | Dispatch idempotency (execution_id dedup at launch) | Prevents replay storm | Application |
| 2 | SpendTracker wired into execution path | Budget ceiling per org/repo | Application |
| 3 | Replay-mode detection in projection | Prevents catch-up side effects | Infrastructure |
| 4 | Concurrent task pool limit | Prevents resource exhaustion | Infrastructure |
| 5 | Per-repo rate limit (durable) | Prevents noisy-neighbor monopoly | Domain |
| 6 | ExpectedVersion.NoStream on execution streams | Prevents duplicate streams | Infrastructure |
