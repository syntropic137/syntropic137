# 10 - Architectural Fitness Functions

**Status:** COMPLETE (design), PENDING (implementation)

## Purpose

Fitness functions are automated checks that enforce architectural
invariants. They run in CI and locally, preventing future features from
reintroducing the class of bugs found in this audit.

---

## F1: Projection Purity Check

**Invariant:** Projections must not import or call side-effecting services.

**Mechanism:** Static import analysis. Scan all files in
`slices/*/projection.py` across all bounded contexts. Flag any projection
that imports from:
- `_wiring.py` (dispatchers, services)
- `asyncio.create_task`
- HTTP clients, API clients
- Any class with `Dispatcher`, `Executor`, `Runner`, `Launcher` in name

**Known violations:**
- `dispatch_triggered_workflow/projection.py` imports and calls
  `execution_service.run_workflow()`

**Implementation:** Python script in `scripts/` or a `just` recipe.
Can use AST parsing or simple grep.

```bash
# Pseudocode
for projection in $(find . -path "*/slices/*/projection.py"); do
  if grep -qE "run_workflow|create_task|Dispatcher|httpx" "$projection"; then
    echo "FAIL: $projection has side-effect imports"
    exit 1
  fi
done
```

---

## F2: Restart Safety Integration Test

**Invariant:** Restarting the service with N open PRs produces zero new
workflow executions.

**Mechanism:** Integration test that:
1. Seeds the event store with 50 TriggerFired events (simulating history)
2. Seeds projection checkpoints to position 50 (simulating prior run)
3. Starts the subscription coordinator
4. Waits for catch-up to complete
5. Asserts: zero calls to `run_workflow()` (mock the dispatcher)
6. Asserts: zero new ExecuteWorkflowCommand created

**Variant - checkpoint loss:**
1. Seeds the event store with 50 TriggerFired events
2. Does NOT seed checkpoints (simulating loss)
3. Starts the subscription coordinator
4. Asserts: zero calls to `run_workflow()` even during full replay

This variant will FAIL until the Processor To-Do List fix (C1+C2) is
implemented. That's the point - it's a regression test for the fix.

---

## F3: Dedup Durability Check

**Invariant:** Every trigger path has a durable dedup check before
command issuance.

**Mechanism:** Code review checklist enforced by test:
1. Trace from each event source (webhook, events poll, check-run poll)
   to `EvaluateWebhookHandler._fire_trigger()`
2. At each step, verify a durable (Postgres-backed) dedup check exists
3. Verify the dedup check cannot be bypassed by fail-open behavior
   reaching the fire path without any durable guard

**Implementation:** Integration test with Postgres dedup + Redis down.
Submit same event twice. Assert exactly one trigger fire.

---

## F4: Replay Safety Integration Test

**Invariant:** Replaying all events from the event store produces no
side effects.

**Mechanism:** Integration test that:
1. Seeds event store with full history (100+ events of various types)
2. Creates a fresh subscription coordinator with all projections
3. Replays from position 0
4. Mocks ALL side-effecting services (dispatchers, API clients)
5. Asserts: zero calls to any mock
6. Asserts: all projection read models are correctly built

This is the "pure reconstruction" test. If any projection calls an
external service during replay, this test fails.

---

## F5: Error Propagation Check

**Invariant:** No `except Exception: pass` or `except Exception: log only`
in critical paths.

**Mechanism:** Static analysis. Scan for bare exception handlers in:
- Projection handlers
- Background tasks
- Event pipeline
- Startup/lifecycle code

**Known violations:**
- `ListSessionsProjection.mark_orphaned_as_failed()` - `except Exception: pass`
- `WorkflowExecutionProcessor._handle_failure()` - swallows cleanup errors
- `execute_workflow_endpoint()` background task - no exception wrapper

**Implementation:** Grep + allowlist.

```bash
# Find bare exception swallowing
grep -rn "except Exception:" --include="*.py" | \
  grep -v "logger\.\(error\|exception\|critical\)" | \
  grep -v "# allowed:" 
```

---

## F6: In-Memory Correctness Guard Audit

**Invariant:** No in-memory-only state is used for correctness guarantees
that must survive restart or multi-instance deployment.

**Mechanism:** Code review checklist. For each `asyncio.Lock`, `dict`
cache, or `set` used for dedup/concurrency:
1. Is it used for correctness or just performance?
2. What happens if it's lost (restart)?
3. What happens with two instances?

**Known violations:**
- `_fire_locks` (asyncio.Lock dict) - correctness, breaks on restart/multi-instance
- `_dispatch_timestamps` (rate limit) - safety net, acknowledged trade-off
- `_pending` (debouncer) - deferred triggers lost on restart

**Implementation:** Annotate each in-memory state with a comment:
```python
# CORRECTNESS: requires distributed lock for multi-instance
# PERFORMANCE: safe to lose on restart
# ACKNOWLEDGED: documented trade-off, see architectural-fitness.md
```

Static check: grep for `asyncio.Lock()` and `dict[` in handler files,
verify each has a classification comment.

---

## F7: Cost Ceiling Check

**Invariant:** No more than N workflow executions can be created per
repo per hour without explicit override.

**Mechanism:** Durable rate limiter at the last gate before spend.

**Implementation:**
1. Postgres-backed counter: `(repo_id, hour_bucket) -> count`
2. Checked in `WorkflowDispatchProcessor` (after C2 fix) or
   `ExecuteWorkflowHandler` (interim)
3. Default limit: configurable per trigger rule, with global fallback
4. Integration test: submit N+1 dispatch requests for same repo in
   same hour, assert Nth+1 is rejected

---

## F8: Aggregate Guard Check

**Invariant:** Aggregate command handlers must validate preconditions
before emitting events.

**Mechanism:** Unit test per aggregate:
1. For `TriggerRuleAggregate.record_fired()`: assert it rejects when
   status != ACTIVE (currently it does not - this test will fail until
   H3 fix is implemented)
2. For `WorkflowExecutionAggregate.start_execution()`: assert it rejects
   when already started

**Implementation:** Standard unit tests in the domain test suite.

---

## F9: Background Task Exception Wrapper

**Invariant:** Every `background_tasks.add_task()` closure must handle
both `Result` errors AND raised exceptions.

**Mechanism:** Static check or wrapper pattern.

**Implementation:** Create a standard wrapper:
```python
async def safe_background_task(
    coro: Coroutine[Any, Any, Any],
    task_name: str,
) -> None:
    try:
        result = await coro
        if isinstance(result, Err):
            logger.error("Background task %s failed: %s", task_name, result)
    except Exception:
        logger.exception("Background task %s raised exception", task_name)
```

Fitness check: grep for `background_tasks.add_task` and verify each
uses the wrapper.

---

## F10: Bounded Context Independence Check

**Invariant:** Bounded contexts do not import from each other's
domain or slice modules.

**Mechanism:** Import graph analysis.

**Implementation:**
```bash
# Check for cross-context imports
for ctx in orchestration agent_sessions github artifacts organization; do
  for other in orchestration agent_sessions github artifacts organization; do
    if [ "$ctx" != "$other" ]; then
      grep -rn "from syn_domain.contexts.$other" \
        "packages/syn-domain/src/syn_domain/contexts/$ctx/" && \
        echo "FAIL: $ctx imports from $other"
    fi
  done
done
```

**Current status:** Clean (no circular dependencies found in this audit).
This fitness function prevents future violations.

---

## Implementation Priority

| # | Fitness function | Prevents | Effort | When to add |
|---|-----------------|----------|--------|-------------|
| F2 | Restart safety test | Replay storm | Medium | With C1+C2 fix |
| F4 | Replay safety test | Projection side effects | Medium | With C1+C2 fix |
| F1 | Projection purity | Future side effects in projections | Small | Immediately |
| F5 | Error propagation | Silent failures | Small | Immediately |
| F9 | Background task wrapper | Ghost executions | Small | Immediately |
| F7 | Cost ceiling | Unbounded spend | Medium | With H1 fix |
| F8 | Aggregate guards | Bypassed invariants | Small | With H3 fix |
| F6 | In-memory audit | Correctness on restart | Small | Immediately |
| F3 | Dedup durability | Fail-open bypass | Medium | After F2 |
| F10 | Context independence | Cross-context coupling | Small | Immediately |

**Quick wins (can add to CI now):** F1, F5, F6, F9, F10
**Add with structural fixes:** F2, F3, F4, F7, F8
