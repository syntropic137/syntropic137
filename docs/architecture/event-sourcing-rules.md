# Event Sourcing Rules for Contributors

> Moved verbatim from AGENTS.md / CLAUDE.md (CLAUDE.md diet, owner review). AGENTS.md keeps a one-line summary and a link here.

## Containerized Agent Execution

Claude CLI runs INSIDE Docker containers, not on the host. `WorkspaceService` creates isolated workspaces, injects secrets during a setup phase (ADR-024), then clears them before agent execution. Agent stdout (JSONL) is captured externally and flows through the observability pipeline.

## Event Storage

`WorkflowExecutionEngine` is the single owner of event recording. It parses Claude CLI JSONL output and records token usage, tool lifecycle, and subagent lifecycle events. All events keyed by `session_id`.


## Two-Lane Architecture

All state and telemetry flows through two strictly separated lanes:

1. **Lane 1: Event Sourcing (Domain Truth)** - Aggregates are the sole decision-makers for state transitions. Commands go in, events come out. The aggregate owns the rules. Infrastructure handlers react to events, do work, and report results back via new commands.

2. **Lane 2: Observability (Telemetry)** - Token counts, tool traces, timing, stream chunks. Append-only, never replayed for state. Writes to observability recorder, NOT the event store. No interaction with aggregates.

## Long-Running Process Orchestration

When orchestrating multi-step processes (e.g., workflow execution with multiple phases):

**Do NOT** use imperative async/await orchestration:
```python
# WRONG - imperative orchestrator
async def execute(workflow):
    for phase in workflow.phases:
        workspace = await provision_workspace(phase)
        result = await run_agent(workspace)
        await collect_artifacts(result)
```

**DO** use the Processor To-Do List pattern:
- **Aggregate** handles commands and emits events, enforces rules, decides "what's next"
- **To-Do List Projection** (read model) builds a list of pending work from events
- **Processor** reads the to-do list and dispatches commands - zero business logic
- **Infrastructure Handlers** react to commands, do async work, emit result events

Flow: `Event → Projection updates to-do list → Processor reads list → Dispatches command → Handler does work → Emits event → cycle repeats`

Key properties:
- Crash-resilient: to-do list persists, processor restarts and picks up where it left off
- All business logic in aggregates and projections, never in the processor
- Each handler is single-responsibility, <200 LOC, independently testable

## When to Use Which Pattern

| Scenario | Pattern | Example |
|----------|---------|---------|
| Multi-step process with infrastructure work | Processor To-Do List | Workflow execution (provision → run → collect → next phase) |
| Simple command → event → done | Direct aggregate command | Creating a workspace, pausing an execution |
| Querying derived state | Projection (read model) | Dashboard metrics, execution list, session tools |
| Time-based triggers (timeouts, SLA deadlines) | Passage of Time (clock events) | Stale execution detection, phase timeout enforcement |

## Event Consumer Types (Three-Way Split)

> Reference: [CONSUMER-PATTERNS.md](../../lib/event-sourcing-platform/docs/CONSUMER-PATTERNS.md), [ADR-025](../../lib/event-sourcing-platform/docs/adrs/ADR-025-process-manager-pattern.md)

Every event consumer must be exactly one of these types. The distinction is critical for restart safety.

| Type | Base class | Side effects? | Replay-safe? | Purpose |
|------|-----------|---------------|-------------|---------|
| **Projection** | `CheckpointedProjection` | Never | Yes | Build read models (dashboards, query views, metrics) |
| **ProcessManager** | `ProcessManager` | Yes (live only) | Yes | React to events with commands (dispatch workflows, call APIs) |

**Projection** builds derived state from events. Pure, idempotent, replay-safe. `SIDE_EFFECTS_ALLOWED = False`. Replaying the entire event store 1000 times must produce the same result with zero external calls.

**ProcessManager** uses the Processor To-Do List pattern with a hard boundary:
- `handle_event()` -- writes to-do records (pure, runs during replay AND live)
- `process_pending()` -- executes pending items (idempotent, runs ONLY when live)
- `SIDE_EFFECTS_ALLOWED = True`
- The coordinator enforces the boundary: `process_pending()` is never called while `is_catching_up` is True

**The critical anti-pattern:** A projection that dispatches commands or calls external APIs in `handle_event()`. This fires side effects during replay, causing duplicate executions on every restart. Use `ProcessManager` instead.

## In-Memory Adapter Safety (ADR-060)

> Reference: [ADR-060](../adrs/ADR-060-restart-safe-trigger-deduplication.md)

In-memory state is dangerous in production -- it's lost on restart, causing duplicate work, lost dedup keys, or orphaned executions. All in-memory adapters inherit from `InMemoryAdapter` (`packages/syn-adapters/src/syn_adapters/in_memory.py`), which raises `InMemoryAdapterError` outside test/offline environments.

**Rules:**
- All test-only in-memory adapters MUST inherit `InMemoryAdapter` (or call `assert_test_only()` for dataclasses)
- The canonical check is `settings.uses_in_memory_stores` (= `is_test or is_offline`)
- Production wiring MUST fail-fast if no durable backend is available -- never silently fall back to in-memory
- No exceptions -- every in-memory adapter is guarded

**Key files:**
- `packages/syn-adapters/src/syn_adapters/in_memory.py` -- Base class and standalone check
- `apps/syn-api/src/syn_api/_wiring.py` -- Adapter selection (Postgres > Redis > fail-fast)

## Projection Consistency in Processor Loops

When a processor needs immediate feedback from its own commands (e.g., "I just completed phase 1, what's the next todo?"), the event subscription pipeline introduces eventual consistency delays. Two strategies:

- **In-process synchronous projection:** The processor maintains a local projection instance. After each `repository.save(aggregate)`, it reads the aggregate's uncommitted events and applies them directly to the local projection. The persistent projection catches up asynchronously for external consumers (dashboard, API). This is the preferred approach for process-local to-do lists.
- **Never** poll the persistent projection waiting for it to catch up - this creates fragile timing dependencies.

## Crash Recovery and Restart Guarantees

The Processor To-Do List pattern is crash-resilient by design:
- **Domain state** is in the event store - fully recoverable by replaying events onto the aggregate
- **To-Do list** is a projection - rebuilt from the event stream on restart (catch-up subscription)
- **Infrastructure state** (active Docker containers, open connections) is ephemeral and NOT in the event stream. On crash, infrastructure is assumed lost. The processor re-provisions from the last completed domain event.
- **Key invariant:** If the processor crashes between "handler did work" and "command reported to aggregate," the to-do item still shows as pending. On restart, the handler re-executes. Handlers MUST be idempotent - re-provisioning a workspace or re-collecting artifacts should be safe.

## Handler Idempotency Rule

Infrastructure handlers MUST be idempotent. If called twice with the same todo item:
- `WorkspaceProvisionHandler`: Creates a new workspace (old one is gone after crash) - safe
- `AgentExecutionHandler`: Re-runs the agent from scratch - safe (stateless container)
- `ArtifactCollectionHandler`: Re-collects from workspace - safe (idempotent writes)

The aggregate enforces ordering via command guards (e.g., reject `CompletePhaseCommand` if phase not in RUNNING state).

## What Goes in the Event Store vs. What Doesn't

| In Event Store (Lane 1) | NOT in Event Store |
|---|---|
| Phase started/completed | Docker container IDs |
| Workspace provisioned (fact that it happened) | Active workspace handles |
| Agent execution completed (tokens, cost, duration) | JSONL stream bytes |
| Artifacts collected (artifact IDs) | Temporary file paths |
| Workflow completed/failed | In-memory caches |

Rule: If you need it after a restart, it must be an event. If it's only needed during the current process lifecycle, hold it in the processor.

## Subscription Architecture

Production uses `CoordinatorSubscriptionService` with per-projection checkpoints ([ADR-055](../adrs/ADR-055-projection-checkpoint-coordinator-architecture.md)). Legacy `EventSubscriptionService` ([ADR-010](../adrs/ADR-010-event-subscription-architecture.md)) is deprecated. See `create_coordinator_service()` in `packages/syn-adapters/src/syn_adapters/subscriptions/coordinator_service.py` for the 12-projection registry.

## Background Task Error Handling

FastAPI `BackgroundTasks` silently swallow exceptions and `Result` errors. Any `background_tasks.add_task()` closure MUST check `isinstance(result, Err)` and log explicitly. Reference pattern: `apps/syn-api/src/syn_api/routes/executions/commands.py:200-217`.

## Object Storage Bucket Initialization

MinIO buckets MUST be created eagerly at startup via `ensure_ready()`, not lazily on first upload. Downloads fail with `NoSuchBucket` before any upload happens. See `lifecycle.py:_init_artifact_storage()` and [ADR-012](../adrs/ADR-012-artifact-storage.md).

## Rules

- Aggregates MUST be the decision-makers - never let an engine/service decide "what's next"
- State MUST be derived from events - no mutable in-memory state (no `ExecutionContext` pattern)
- Observability MUST be separate from domain - telemetry never flows through aggregates
- Long-running processes MUST use Processor To-Do List - no imperative async loops

## References

- Martin Dilger, *Understanding Event Sourcing* - Ch. 37: Processor To-Do List pattern
- Event Modeling specification: https://eventmodeling.org/posts/what-is-event-modeling/
- To-Do List + Passage of Time patterns: https://event-driven.io/en/to_do_list_and_passage_of_time_patterns_combined/

