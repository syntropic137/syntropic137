# Audit Task List and Status

Last updated: 2026-04-14T09:40

## Legend

- [ ] Not started
- [~] In progress
- [x] Complete
- [!] Blocked

---

## Phase 1: Understand -- COMPLETE

### 1.1 Inventory trigger paths
- [x] Map every place a workflow can be started
- [x] For each path: identify source of truth, dedup mechanism, idempotency key, restart safety
- [x] Document in [01-ownership.md](01-ownership.md)

### 1.2 Classify handlers by replay safety
- [x] List every handler/projection/service in the trigger pipeline
- [x] Classify each as: pure reconstruction, decision-making, or side-effect execution
- [x] Identify handlers that mix categories
- [x] Document in [02-replay-safety.md](02-replay-safety.md)

### 1.3 Audit idempotency keys and enforcement
- [x] Identify the dedup key for each trigger source
- [x] Determine where each dedup check is enforced
- [x] Find all "assume won't happen twice" patterns
- [x] Document fail-open behavior
- [x] Document in [03-idempotency.md](03-idempotency.md)

### 1.4 Trace startup and recovery behavior
- [x] Walk through the full startup sequence
- [x] Trace subscription coordinator catch-up behavior
- [x] Trace WorkflowDispatchProjection replay behavior
- [x] Identify where startup reconciliation becomes fresh trigger intake
- [x] Run the "5 restarts in 2 minutes" mental model
- [x] Run the "cold start with 200 open PRs" mental model
- [x] Document in [04-startup-recovery.md](04-startup-recovery.md)

### 1.5 Audit temporal definitions
- [x] For each event source, document what "new" means
- [x] For each poller, document cursor persistence and durability
- [x] Identify ordering assumptions that are stronger than reality
- [x] Document in [05-temporal.md](05-temporal.md)

### 1.6 Map boundary clarity
- [x] Map every file in the trigger pipeline to its concern
- [x] Determine whether pollers publish facts or issue commands
- [x] Trace convergence point for webhook + polling duplicate facts
- [x] Identify the spaghetti hub
- [x] Document in [06-boundaries.md](06-boundaries.md)

### 1.7 Audit cost control gates
- [x] Identify top 5 code paths where duplicates burn money
- [x] For each expensive action, identify the last gate before spend
- [x] Assess whether each gate is durable, atomic, and sufficient
- [x] Check for rate limits and budget ceilings
- [x] Document in [07-cost-control.md](07-cost-control.md)

---

## Phase 1.5: ESP Platform Audit -- COMPLETE

### 1.8 Audit event-sourcing-platform base classes
- [x] Audit CheckpointedProjection base class and interface
- [x] Audit SubscriptionCoordinator replay behavior
- [x] Check for ProcessManager / Saga / Processor concepts (none exist)
- [x] Check EventEnvelope for replay flag (none exists)
- [x] Map ESP module structure
- [x] Check for built-in fitness functions (none exist)
- [x] Design ESP enhancements: DispatchContext, ProcessManager, purity marker, fitness module
- [x] Document in [11-esp-platform-audit.md](11-esp-platform-audit.md)

---

## Phase 2: Fix -- COMPLETE (analysis), IN PROGRESS (implementation)

### 2.1 Consolidate findings
- [x] Prove or disprove each of the 7 invariants
- [x] List all three-way-split violations with severity
- [x] Walk through the 20-restarts-in-1-hour stress scenario
- [x] Document in [08-findings.md](08-findings.md)

### 2.2 Map current vs ideal pipeline
- [x] Draw the current trigger pipeline with file references
- [x] Draw the ideal pipeline with clean three-way separation
- [x] Gap analysis between current and ideal (10 gaps identified)
- [x] Document in [09-pipeline-map.md](09-pipeline-map.md)

### 2.3 Design ESP gap plan
- [x] Identify 7 gaps in ESP (replay awareness, ProcessManager, purity, fitness, docs, VSA, test kit)
- [x] Design full implementation plan with 7 sub-phases (0.1-0.7)
- [x] Map file changes for each phase (new files, modified files, VSA rules)
- [x] Define dependency graph and timeline (7-10 working days)
- [x] Define success criteria (7 checkpoints)
- [x] Document in [12-esp-gap-plan.md](12-esp-gap-plan.md)

### 2.4 Create shared vocabulary
- [x] Create ES glossary with definitions, patterns, and rules
- [x] Define: Aggregate, Projection, Processor/ProcessManager, Three-Way Split
- [x] Document anti-patterns: projection with side effects, god service, in-memory locks
- [x] Document safety patterns: content-based dedup, ExpectedVersion, checkpoints
- [x] Published at [docs/architecture/es-glossary.md](../../architecture/es-glossary.md)

### 2.5 Build and execute fix plan
- [x] Prioritize fixes by severity (critical / high / medium)
- [x] Assign each fix to domain, application, or infrastructure layer
- [x] Create project plan with phases, dependencies, timeline: [PROJECT-PLAN.md](PROJECT-PLAN.md)
- [ ] Create GitHub issues for each fix
- [x] Implement Phase 0.1: DispatchContext with global_nonce boundary -- **DONE**
- [x] Implement Phase 0.2: ProcessManager base class -- **DONE**
- [x] Implement Phase 0.3: SIDE_EFFECTS_ALLOWED purity marker -- **DONE**
- [x] Implement Phase 0.4: Built-in fitness module (whitelist-based) -- **DONE**
- [x] Implement Phase 0.5: Documentation (CONSUMER-PATTERNS.md, ADR-025) -- **DONE**
- [x] Implement Phase 0.6: VSA validator extensions (VSA032+VSA033) -- **DONE**
- [x] Implement Phase 0.7: Test kit (ProcessManagerScenario, IdempotencyVerifier) -- **DONE**
- [x] Write tests for ESP Phases 0.1-0.7 (48 new tests, 194 total pass) -- **DONE**
- [x] Commit, push, open PR for ESP -- **DONE** (syntropic137/event-sourcing-platform#274)
- [x] Design Syn137 migration plan -- **DONE** ([13-syn137-migration-plan.md](13-syn137-migration-plan.md))
- [ ] Implement Phase A: stop the bleeding (A1-A3) -- blocked on ESP PR merge
- [ ] Implement Phase B: structural fix (B1-B3) -- blocked on ESP PR merge
- [ ] Implement Phase C: cost safety (C1-C3)
- [ ] Implement Phase D: error handling (D1-D3)
- [ ] Implement Phase E: hygiene (E1-E6)

---

## Phase 3: Prevent -- DESIGN COMPLETE, IMPLEMENTATION PENDING

### 3.1 Design fitness functions
- [x] F1: Projection purity check (no side-effect imports)
- [x] F2: Restart safety integration test
- [x] F3: Dedup durability check
- [x] F4: Replay safety integration test
- [x] F5: Error propagation check (no silent exception swallowing)
- [x] F6: In-memory correctness guard audit
- [x] F7: Cost ceiling check (per-repo rate limit)
- [x] F8: Aggregate guard check
- [x] F9: Background task exception wrapper
- [x] F10: Bounded context independence check
- [x] Document in [10-fitness-functions.md](10-fitness-functions.md)

### 3.2 Implement fitness functions
- [x] F1: Projection purity check -- **DONE** (shipped in ESP fitness module, whitelist-based)
- [x] F4: Replay safety check -- **DONE** (shipped in ESP fitness module)
- [ ] Quick wins remaining: F5, F6, F9, F10 (Syn137-specific)
- [ ] Add with structural fixes: F2, F3, F7, F8
- [ ] Wire ESP fitness into `just fitness-check`
- [ ] Verify they catch known violations

### 3.3 Update AGENTS.md
- [ ] Add three-way split principle to non-negotiable rules
- [ ] Add architectural fitness reference for future development
- [ ] Add restart safety test to pre-PR checklist

---

## Status Summary

| Phase | Progress | Blocking issues |
|-------|----------|----------------|
| Phase 1: Understand | **7/7 complete** (verified) | None |
| Phase 1.5: ESP audit | **Complete** | None |
| Phase 2: Fix (analysis) | **4/4 complete** + project plan + ESP gap plan + glossary | None |
| Phase 2: Fix (ESP impl) | **COMPLETE** - PR syntropic137/event-sourcing-platform#274 open | None |
| Phase 2: Fix (Syn137 design) | **COMPLETE** - [13-syn137-migration-plan.md](13-syn137-migration-plan.md) | None |
| Phase 2: Fix (Syn137 impl) | 0/5 phases (A-E) | Blocked on ESP PR merge |
| Phase 3: Prevent (design) | **1/3 complete** (10 fitness functions designed) | None |
| Phase 3: Prevent (implementation) | **2/10 done** (F1 purity, F4 replay safety shipped in ESP) | Remaining need Syn137 fixes |

### Audit status: ESP COMPLETE, SYN137 MIGRATION DESIGNED

Analysis complete. 18 documents produced. ESP implementation complete:
- All 7 ESP phases implemented (DispatchContext, ProcessManager, coordinator gating, fitness, docs, VSA, test kit)
- 194 Python tests pass (48 new + 146 existing), 251 Rust tests pass (3 new VSA rules)
- PR syntropic137/event-sourcing-platform#274 open for review
- Syn137 migration plan designed in [13-syn137-migration-plan.md](13-syn137-migration-plan.md)
- **Next:** Merge ESP PR, then implement Phases A+B in syntropic137
- After ESP PR: Syn137 migration (Phases A-E)

### Verification pass (2026-04-13T16:06)
- [x] Confirmed projection.py:98 dispatches, line 100-107 checkpoints after
- [x] Confirmed _on_trigger_fired re-raises on failure (line 161) - checkpoint NOT advanced on failure (corrected in 08-findings.md)
- [x] Confirmed TriggerRuleAggregate.record_fired() has zero guards (line 221-237)
- [x] Confirmed can_fire() exists (line 257) but is never called
- [x] Confirmed WorkflowExecutionAggregate.start_execution() guard is per-instance only (line 160)

---

## Critical Findings Summary

### Invariant Scorecard

| # | Invariant | Status |
|---|-----------|--------|
| 1 | Trigger has stable content-based dedup key | **PROVEN** |
| 2 | No launch without atomic dedup key recording | **DISPROVEN** |
| 3 | Startup reconciliation cannot issue unseen-unproven work | **DISPROVEN** |
| 4 | Projection rebuild is side-effect free | **DISPROVEN** |
| 5 | Polling and webhooks converge on same trigger identity | **PROVEN** |
| 6 | At most one active workflow per logical unit of work | **DISPROVEN** |
| 7 | Expensive actions guarded at last responsible moment | **DISPROVEN** |

### Root Causes (Blocking Release)

1. **WorkflowDispatchProjection** is a process manager masquerading as a
   projection. It dispatches workflows during replay. No replay-vs-live
   guard exists anywhere in the codebase.

2. **Zero cost gates** in the dispatch chain. SpendTracker exists but is
   not wired. No budget ceiling, no per-repo rate limit.

3. **Aggregate not enforcing invariants.** TriggerRuleAggregate.record_fired()
   has zero guards. can_fire() exists but is never called.

4. **No dispatch idempotency.** BackgroundWorkflowDispatcher and
   ExecuteWorkflowHandler have no dedup. Each call creates a new execution.

### What's Working Well

1. Content-based dedup keys (observe/decide boundary is clean)
2. Pollers publish facts, not commands
3. Webhook/polling convergence at EventPipeline is sound
4. Safety guards 1-4 are durable (Postgres-backed)
5. ETag-based cursor persistence for Events API poller
6. EventPipeline as single convergence point

### Prioritized Fix List (Draft)

| Priority | Fix | Impact |
|----------|-----|--------|
| P0 | Make WorkflowDispatchProjection pure (to-do list pattern) | Eliminates replay storm |
| P0 | Add dispatch idempotency (execution_id dedup at launch) | Prevents all duplicate launches |
| P1 | Wire SpendTracker into execution path | Budget ceiling before spend |
| P1 | Add replay-mode detection to subscription coordinator | Structural fix for all projections |
| P1 | Move trigger invariants into aggregate (call can_fire) | Domain guards |
| P2 | Add concurrent task pool limit to dispatcher | Prevents resource exhaustion |
| P2 | Add per-repo durable rate limit | Prevents noisy-neighbor |
| P2 | Add ExpectedVersion.NoStream to execution streams | Prevents duplicate streams |
| P3 | Implement Events API pagination | Prevents silent event loss |
| P3 | Fix dedup TTL mismatch (settings vs adapter) | Consistency |
| P3 | Persist pending SHAs for check-run poller | Cursor durability |
