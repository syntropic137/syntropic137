# Restart Safety Audit - Task List

Last updated: 2026-04-14T15:52

## Completed

- [x] Phase 1: Understand (7 audit documents, all invariants mapped)
- [x] Phase 1.5: ESP platform audit (gaps identified, design complete)
- [x] Phase 2 analysis: findings, pipeline map, gap plan, glossary, project plan
- [x] ESP Phase 0.1: DispatchContext with global_nonce boundary
- [x] ESP Phase 0.2: ProcessManager base class (To-Do List pattern)
- [x] ESP Phase 0.3: SIDE_EFFECTS_ALLOWED purity marker
- [x] ESP Phase 0.4: Fitness module (whitelist-based projection purity, process manager check, replay safety)
- [x] ESP Phase 0.5: Documentation (CONSUMER-PATTERNS.md, ADR-025, AGENTS.md, PLATFORM-PHILOSOPHY.md)
- [x] ESP Phase 0.6: VSA validator rules (VSA032 ProjectionPurityRule, VSA033 ProcessManagerStructureRule)
- [x] ESP Phase 0.7: Test kit (ProcessManagerScenario, IdempotencyVerifier)
- [x] ESP tests: 48 new tests (194 total pass), 3 new Rust tests (251 total pass)
- [x] ESP PR opened: syntropic137/event-sourcing-platform#274 (36 files, 2912 insertions)
- [x] ESP PR CI fixes: pyright reportPrivateUsage, object ratchet, Copilot review comments
- [x] ESP PR OSV fix: follow-redirects 1.16.0, rand 0.8.5 justified ignore, stale ignores cleaned
- [x] Syn137 migration plan designed: [13-syn137-migration-plan.md](13-syn137-migration-plan.md)
- [x] Audit markdown artifacts synced to reflect implementation status

## In Progress

- [x] Update ESP submodule pointer in Syn137 (4bea815)
- [x] Syn137 Phase A: Stop the bleeding
  - [x] A2: Semaphore-bounded concurrency (MAX_CONCURRENT=10) on BackgroundWorkflowDispatcher
  - [x] A3: Background task exception wrapper in execute_workflow_endpoint
  - [x] A4: InMemoryDedupAdapter fallback logs ERROR (fail-open with warning)
  - [x] A1: Dispatch idempotency via save_new() + StreamAlreadyExistsError -> DuplicateExecutionError
- [x] Syn137 Phase B: Structural fix
  - [x] B1+B2: WorkflowDispatchProjection converted to ProcessManager (handle_event pure, process_pending live-only)
  - [x] B3: TriggerRuleAggregate.record_fired() now guards with can_fire()
- [x] Syn137 Phase C: Cost safety - PR #681
  - [x] C1: SpendTracker budget check wired into dispatch chain (_BudgetChecker protocol)
  - [x] C2: Per-hour dispatch rate limit (50/hr default, SYN_POLLING_MAX_DISPATCHES_PER_HOUR)
  - [x] C3: ExpectedVersion.NoStream (done in PR #676 via save_new)
- [x] Syn137 Phase D: Error handling - PR #679
  - [x] D1a: reconcile_running_sessions exception logging
  - [x] D1b: debouncer task done callback
  - [x] D1c: lifecycle recovery task done callback
  - [x] D1d: postgres_dedup cleanup task done callback
- [x] Syn137 Phase E: Hygiene - PR #680
  - [x] E2: Events API pagination (up to 10 pages)
  - [x] E3: Dedup TTL alignment (Postgres now uses settings value)
  - [x] E4: PostgresPendingSHAStore (durable across restarts)
  - [x] E5: Prune _fire_locks dict (bounded to 1000)
  - [x] E5-adj: Bound _sig_failures dict (bounded to 10k IPs)
  - Deferred: E1 (distributed locks - multi-instance only)
- [x] Wire ESP fitness into ci/fitness (11 new tests: purity, ProcessManager, regression guard)
- [x] Fix handle_event override signatures (DispatchContext parameter on all 6 adapter overrides)
- [x] Address Copilot review comments: query() for pending records, delete_all(), honest docstring, ValueError on can_fire()
- [x] Upgrade pytest 9.0.2 -> 9.0.3 (GHSA-6w46-j5rx-g56g fixed, #677 closed)

## Completed (this session)

- [x] Deep audit: error handling patterns (5 findings)
- [x] Deep audit: aggregate invariant enforcement (10 aggregates, 1 HIGH issue)
- [x] Deep audit: in-memory state patterns (12 components, 5 critical/high)
- [x] Consolidated findings in [14-deep-audit-findings.md](14-deep-audit-findings.md)
- [x] Multi-instance readiness assessment (not safe today - 7 components need work)
- [x] PR #679 (Phase D - error handling) merged
- [x] PR #680 (Phase E - hygiene) merged
- [x] PR #681 (Phase C - cost safety) merged
- [x] PR #689 (D3 - trigger lifecycle events) merged
- [x] PR #690 (Fitness functions F5, F6) merged
- [x] GitHub issues created for all deferred gaps (#682-#688)
- [x] All Copilot review comments addressed on all PRs

## Remaining Work (not blocked)

- [x] Create GitHub issues for deferred gaps (#682-#688)
- [x] Update AGENTS.md with three-way split principle (#688)
- [ ] Commit Syn137 audit documents to this branch
- [x] Add InMemoryDedupAdapter fail-closed fix (InMemoryAdapter base class, ADR-060 s5+s6)

## Fitness Functions

- [x] F1: Projection purity (shipped in ESP fitness module)
- [x] F2: Restart safety (test_restart_safety.py - ProcessManagerScenario replay test)
- [x] F3: Dedup durability (test_dedup_durability.py - structural pipeline wiring checks)
- [x] F4: Replay safety (shipped in ESP fitness module)
- [x] F5: Error propagation check (PR #690)
- [x] F6: In-memory correctness guard audit (PR #690)
- [x] F7: Cost ceiling (test_cost_ceiling.py - rate limit + budget wiring + config defaults)
- [x] F8: Aggregate guard (test_aggregate_guards.py - @command_handler precondition checks)
- [x] F9: Background task exception wrapper (already covered by existing test)
- [x] F10: Bounded context independence check (already covered by existing test)

## Architecture Gaps Found (from audit)

| Gap | Severity | Status |
|-----|----------|--------|
| WorkflowDispatchProjection dispatches during replay | Critical | ESP fix complete, Syn137 migration designed |
| Zero dispatch idempotency | Critical | Fix designed (Phase A1) |
| Zero cost gates in dispatch chain | Critical | Fix designed (Phase C) |
| TriggerRuleAggregate.record_fired() has zero guards | High | Fix designed (Phase B3) |
| In-memory _fire_locks break on multi-instance | Medium | Fix designed (Phase E1) |
| Silent error swallowing in critical paths | Medium | Fix designed (Phase D1) |
| Events API no pagination (misses events) | Low | Fix designed (Phase E2) |
| Dedup TTL mismatch (settings vs adapter) | Low | Fix designed (Phase E3) |
| Pending SHAs not persisted | Low | Fix designed (Phase E4) |
| Dead last_event_id code | Low | Fix designed (Phase E6) |
| reconcile_running_sessions swallows exceptions | High | Fix designed (Phase D1) |
| debouncer.py task exception loss | High | Fix designed (Phase D1) |
| lifecycle.py recovery loop exception loss | High | Fix designed (Phase D1) |
| InMemoryDedupAdapter silent production fallback | Medium | NEW - add to Phase A |
| _sig_failures dict unbounded growth | Low | Fix designed (Phase E5-adjacent) |
| No multi-instance support (7 components) | Medium | Future phase |

## Documents Produced (19 total)

1. [01-ownership.md](01-ownership.md) - Trigger path inventory
2. [02-replay-safety.md](02-replay-safety.md) - Handler replay safety classification
3. [03-idempotency.md](03-idempotency.md) - Idempotency key audit
4. [04-startup-recovery.md](04-startup-recovery.md) - Startup and recovery behavior
5. [05-temporal.md](05-temporal.md) - Temporal definition audit
6. [06-boundaries.md](06-boundaries.md) - Boundary clarity map
7. [07-cost-control.md](07-cost-control.md) - Cost control gate audit
8. [08-findings.md](08-findings.md) - Consolidated findings (5/7 invariants broken)
9. [09-pipeline-map.md](09-pipeline-map.md) - Current vs ideal pipeline
10. [10-fitness-functions.md](10-fitness-functions.md) - 10 fitness function designs
11. [11-esp-platform-audit.md](11-esp-platform-audit.md) - ESP platform audit
12. [12-esp-gap-plan.md](12-esp-gap-plan.md) - ESP 7-phase implementation plan
13. [13-syn137-migration-plan.md](13-syn137-migration-plan.md) - Syn137 ProcessManager migration
14. [PROJECT-PLAN.md](PROJECT-PLAN.md) - Master fix plan (Phases 0-E)
15. [TASKS.md](TASKS.md) - Detailed task tracking
16. [docs/architecture/es-glossary.md](../../architecture/es-glossary.md) - ES shared vocabulary
17. [docs/architecture/architectural-fitness.md](../../architecture/architectural-fitness.md) - Fitness function reference
18. [14-deep-audit-findings.md](14-deep-audit-findings.md) - Error handling, aggregate guards, in-memory state
19. This file (task-list.md) - Cron-tracked progress
