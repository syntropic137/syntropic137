# Architectural Fitness Fix Plan

**Created:** 2026-04-13
**Goal:** Make the trigger/dispatch pipeline reliable, maintainable, and
scalable so the system can be released with confidence.

## Executive Summary

The audit found **5 of 7 architectural invariants broken**. The root cause
is a single component - `WorkflowDispatchProjection` - acting as a process
manager disguised as a read model. It dispatches real workflows during
event replay with zero guards, zero idempotency, and zero cost controls.

Additionally: ghost executions from unhandled background task exceptions,
silent data corruption from swallowed errors, and in-memory correctness
locks that break on multi-instance deployment.

The good news: the observe/decide boundary is clean. Pollers publish facts,
dedup keys are content-based, webhook/polling convergence is sound. The
disease is specifically at the **decide/execute boundary**.

## What's Working Well (Do Not Touch)

- Content-based dedup keys (`dedup_keys.py`)
- `EventPipeline.ingest()` as single convergence point
- Pollers publish `NormalizedEvent` facts, not commands
- Safety guards 1-4 (durable, Postgres-backed)
- ETag-based cursor persistence for Events API poller
- Bounded context independence (no circular deps)
- Async task tracking (dispatcher, lifecycle, pipeline)

---

## Strategy: Build from the Ground Up

Instead of patching Syn137, fix the event-sourcing-platform (ESP) first.
The architectural gaps exist because ESP provides `CheckpointedProjection`
for read models but nothing for process managers. When Syn137 needed a
process manager, the only available base class was a projection. The
framework made the bug the path of least resistance.

**Build order:**
1. **ESP enhancements** (Phase 0) - DispatchContext, ProcessManager base class
2. **Syn137 inherits the fix** (Phases A-E) - refactor to use new base classes

This way every future system built on ESP gets correct separation of
concerns by construction. See [11-esp-platform-audit.md](11-esp-platform-audit.md)
for the full ESP audit.

---

## Phase 0: ESP Foundation -- COMPLETE

All changes in `lib/event-sourcing-platform/`. PR: syntropic137/event-sourcing-platform#274.
194 Python tests pass (48 new + 146 existing). 251 Rust tests pass (3 new VSA rules).

### 0.1. DispatchContext with replay awareness -- DONE

`DispatchContext` frozen dataclass with `is_catching_up`, `global_nonce`,
`live_boundary_nonce`. Coordinator snapshots head `global_nonce` via
`read_all(forward=False, max_count=1)` before subscribing. Passed to
`handle_event()` as optional `context` parameter (backwards-compatible).

### 0.2. ProcessManager base class -- DONE

`ProcessManager(CheckpointedProjection)` in `core/process_manager.py`.
`handle_event()` (projection side, pure), `process_pending()` (processor
side, live-only), `get_idempotency_key()` (dedup). Coordinator gates
`process_pending()` - never called during catch-up.

### 0.3. Projection purity marker -- DONE

`SIDE_EFFECTS_ALLOWED: ClassVar[bool] = False` on CheckpointedProjection.
ProcessManager overrides to `True`.

### 0.4. Built-in fitness module -- DONE

`event_sourcing/fitness/` with whitelist-based projection purity check
(not blacklist), process manager structure check, replay safety checker.
`PROJECTION_ALLOWED_PREFIXES` frozenset + project-specific `allowed_prefixes`.
TYPE_CHECKING imports always allowed.

### 0.5. Documentation -- DONE

`docs/CONSUMER-PATTERNS.md` and `docs/adrs/ADR-025-process-manager-pattern.md`.
Updated AGENTS.md and PLATFORM-PHILOSOPHY.md.

### 0.6. VSA validator extensions -- DONE

`ProjectionPurityRule` (VSA032) and `ProcessManagerStructureRule` (VSA033)
in `vsa-core/src/validation/consumer_pattern_rules.rs`. Whitelist-based
import checking with configurable `projection_allowed_prefixes` in vsa.yaml.

### 0.7. Test kit extensions -- DONE

`ProcessManagerScenario`, `IdempotencyVerifier`, `IdempotencyResult` in
`testing/process_manager_scenario.py`.

---

## Phase A: Stop the Bleeding -- IN PROGRESS

### A1. Dispatch idempotency check (deferred)

**What:** Before `ExecuteWorkflowHandler.handle()` creates a new aggregate,
check if an execution with this `execution_id` already exists.

**Where:** `apps/syn-api/src/syn_api/_wiring.py` (BackgroundWorkflowDispatcher)
or `packages/syn-domain/.../execute_workflow/ExecuteWorkflowHandler.py`

**How:** Query execution repository for `execution_id`. If stream exists,
log and skip. This prevents replay storms from creating duplicate
executions even if the projection dispatches multiple times.

**Risk:** Low. Additive check, no behavior change for first-time dispatches.

### A2. Concurrent task pool limit -- DONE

**What:** Add a `asyncio.Semaphore` to `BackgroundWorkflowDispatcher` to
bound concurrent workflow tasks.

**Where:** `apps/syn-api/src/syn_api/_wiring.py:554-568`

**How:** Replace unbounded `self._tasks` set with semaphore-gated task
creation. Suggested limit: 10 concurrent executions.

**Risk:** Low. Prevents resource exhaustion during replay storms.

### A3. Background task exception wrapper -- DONE

**What:** Wrap the `_run()` closure in `execute_workflow_endpoint()` to
catch and log raised exceptions (not just `Err` results).

**Where:** `apps/syn-api/src/syn_api/routes/executions/commands.py:463-480`

**How:**
```python
async def _run() -> None:
    try:
        result = await execute(...)
        if isinstance(result, Err):
            logger.error("Workflow execution failed", ...)
    except Exception:
        logger.exception("Workflow execution raised exception for %s", execution_id)
```

**Risk:** Zero. Only adds logging.

### A4. Make InMemoryDedupAdapter fallback fail-closed -- DONE (fail-open with ERROR log)

**What:** The dedup adapter fallback chain (Postgres -> Redis -> InMemory)
silently installs an in-memory adapter on transient DB failures at
startup. This permanently disables dedup durability for the process.

**Where:** `apps/syn-api/src/syn_api/_wiring.py:400-418`

**How:** Replace `InMemoryDedupAdapter` fallback with a fail-closed
pattern: log an ERROR and retry the connection with backoff, or refuse
to start if no durable dedup is available. The in-memory fallback should
only be used when explicitly configured for development.

**Risk:** Low. Changes startup behavior only. Production should always
have Postgres or Redis available.

---

## Phase B: Structural Fix -- DONE

### B1. Make WorkflowDispatchProjection pure -- DONE

**What:** Remove the `run_workflow()` call. The projection should only
write dispatch records with status `pending`.

**Where:** `packages/syn-domain/.../dispatch_triggered_workflow/projection.py`

**Changes:**
- Remove `execution_service` from constructor
- Remove `_on_trigger_fired()` call to `run_workflow()` (line 148)
- Keep the dispatch record write (line 132-140) - this IS the to-do list
- Add `status` field to dispatch record: `pending`, `dispatched`, `failed`

### B2. Create WorkflowDispatchProcessor -- DONE (merged into projection.py as process_pending())

**What:** New component that reads pending dispatch records and fires
workflows with idempotency checks.

**Where:** New file `packages/syn-domain/.../dispatch_triggered_workflow/processor.py`

**Behavior:**
1. On startup and periodically: query dispatch records with `status = pending`
2. For each pending record:
   - Check: does execution_id already exist? (idempotency)
   - Check: is per-repo rate limit ok? (if M1 implemented)
   - If pass: call `run_workflow()`, mark record `dispatched`
   - If fail: mark record `failed` with reason
3. On restart: re-query pending records. Already-dispatched records are
   skipped (status check). Replay-safe by construction.

**Wiring:** Replace the `execution_service` injection in
`get_subscription_coordinator()` with processor startup in lifecycle.

### B3. Move trigger invariants to aggregate -- DONE

**What:** `TriggerRuleAggregate.record_fired()` must call `can_fire()`
and reject if status != ACTIVE.

**Where:** `packages/syn-domain/.../aggregate_trigger/TriggerRuleAggregate.py:221-237`

**Risk:** Low. `can_fire()` already exists (line 257-259), just not called.

---

## Phase C: Cost Safety (2-3 days)

### C1. Wire SpendTracker into execution path

**What:** Budget check before container creation.

**Where:** `WorkflowExecutionProcessor` or `WorkflowDispatchProcessor`

**How:** Call `SpendTracker.check_budget()` before dispatching. The
SpendTracker already exists in `syn-tokens/src/syn_tokens/spend.py`.
It just needs to be injected and called.

### C2. Per-repo durable rate limit

**What:** Max N workflow executions per repo per hour, Postgres-backed.

**Where:** New guard in `safety_guards.py` or in `WorkflowDispatchProcessor`

**How:** Postgres counter table `(repo_id, hour_bucket) -> count`.
Check before dispatch. Configurable per trigger rule with global fallback.

### C3. ExpectedVersion.NoStream on execution streams

**What:** When creating a new execution aggregate, use `ExpectedVersion.NoStream`
to prevent duplicate stream creation.

**Where:** `WorkflowExecutionProcessor` or event store adapter

**Risk:** Low. Standard event sourcing pattern.

---

## Phase D: Error Handling and Observability (2-3 days)

### D1. Fix silent error swallowing and task exception loss

**What:** Replace `except Exception: pass` and add done callbacks to
background tasks in critical paths.

**Where:**
- `ListSessionsProjection.reconcile_running_sessions()` (line 320) -
  replace `pass` with `logger.exception()`. Sessions stuck in "running"
  state when reconciliation fails silently.
- `WorkflowDispatchProjection.handle_event()` (line 110-115) -
  do not advance checkpoint on dispatch failure
- `WorkflowExecutionProcessor._handle_failure()` (line 306-309) -
  escalate cleanup failures
- `debouncer.py:49-56` - add done callback to `asyncio.create_task(_fire())`.
  Trigger firing failures are currently lost silently.
- `lifecycle.py:129` - add done callback to recovery loop task. If
  `_recovery_loop` raises, degraded service recovery stops with no log.
- `postgres_dedup.py:104` - add done callback to cleanup task.
- `conversations/minio.py:116` - add logging to bare `except Exception`.

See [14-deep-audit-findings.md](14-deep-audit-findings.md) for full details.

### D2. Replay-mode flag -- DONE (shipped in ESP Phase 0)

**What:** The coordinator signals catch-up vs. live mode via
`DispatchContext.is_catching_up`. ProcessManager.process_pending()
gated to live-only by the coordinator.

**Where:** `lib/event-sourcing-platform/.../coordinator.py`

**Status:** Implemented in ESP PR syntropic137/event-sourcing-platform#274.

### D3. Trigger lifecycle events

**What:** Add `TriggerDispatchCompleted` and `TriggerDispatchFailed`
events to close the trigger-fire lifecycle loop.

**Where:** `TriggerRuleAggregate`, new events in the github context

**Benefit:** Enables proper audit trail and concurrency tracking.

---

## Phase E: Hygiene (1-2 days)

### E1. Move _fire_locks to distributed lock

**What:** Replace `asyncio.Lock` dict with Postgres advisory lock or
Redis lock for multi-instance safety.

**Where:** `EvaluateWebhookHandler.py:77,125`

### E2. Events API pagination

**What:** Fetch all pages (up to 300 events) instead of just the first 30.

**Where:** `events_api_client.py:80`

### E3. Fix dedup TTL mismatch

**What:** Align `PollingSettings.dedup_ttl_seconds` (24h) with
`PostgresDedupAdapter` default (7d).

### E4. Persist pending SHAs

**What:** Replace `InMemoryPendingSHAStore` with Postgres or Redis adapter.

### E5. Prune _fire_locks dict

**What:** Add TTL-based cleanup to prevent unbounded growth.

### E6. Remove dead last_event_id

**What:** `events_api_client.py:121` stores it but nothing reads it.

---

## Dependency Graph

```
Phase 0 (ESP foundation) -- do first, everything inherits from this
  |
  v
Phase A (stop bleeding) -- can start in parallel with Phase 0
  |
  v
Phase B (structural fix) -- depends on Phase 0 (uses ProcessManager)
  |
  v
Phase C (cost safety) -- depends on B2 (processor exists)
  |
Phase D (error handling) -- can overlap with C
  |
  v
Phase E (hygiene) -- independent, do whenever
```

Phase 0 and Phase A can run in parallel (different repos).
Phases C and D can run in parallel after B is complete.
Phase E items are independent and can be done anytime.

---

## Fitness Functions to Add with Each Phase

| Phase | Fitness function | What it catches |
|-------|-----------------|-----------------|
| A | F9 (background task wrapper) | Ghost executions |
| A | F5 (error propagation check) | Silent failures |
| B | F1 (projection purity) | Side effects in projections |
| B | F2 (restart safety test) | Replay storm |
| B | F4 (replay safety test) | Any projection side effect |
| C | F7 (cost ceiling) | Unbounded spend |
| C | F8 (aggregate guard check) | Bypassed invariants |
| D | F6 (in-memory audit) | Correctness on restart |
| E | F10 (context independence) | Cross-context coupling |
| E | F3 (dedup durability) | Fail-open bypass |

---

## Success Criteria

After all phases, the system must pass these tests:

1. **Restart 20 times with 50 open PRs**: Zero spurious executions
2. **Replay entire event store**: Zero side effects
3. **Same fact via 3 channels**: Exactly one workflow execution
4. **Kill process mid-dispatch**: No duplicate execution on restart
5. **Postgres down during dispatch**: No unguarded spend
6. **Two service instances**: Each workflow executed exactly once
7. **Budget limit reached**: Execution rejected, not silently skipped

---

## Estimated Timeline

| Phase | Status | Repo |
|-------|--------|------|
| 0: ESP foundation | **COMPLETE** - PR syntropic137/event-sourcing-platform#274 | event-sourcing-platform |
| A: Stop the bleeding | **IN PROGRESS** - A2/A3/A4 done, A1 deferred | syntropic137 |
| B: Structural fix | **DONE** - ProcessManager conversion, aggregate guard | syntropic137 |
| C: Cost safety | Not started | syntropic137 |
| D: Error handling | Not started (D2 done in ESP Phase 0) | both |
| E: Hygiene | Not started | syntropic137 |

**Next:** Wire ESP fitness into `just fitness-check`. Then Phase C (cost safety) + Phase D (error handling).
