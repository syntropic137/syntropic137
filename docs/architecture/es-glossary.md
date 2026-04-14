# Event Sourcing Glossary and Architectural Rules

## Purpose

Definitions, patterns, and non-negotiable rules for building reliable
systems on the event-sourcing-platform (ESP). This is the shared vocabulary
for all contributors. If a term is used differently elsewhere in the
codebase, this document is canonical.

Reference: Martin Dilger, *Understanding Event Sourcing* (primary source
for pattern definitions).

---

## Core Concepts

### Event

An immutable fact that something happened in the past. Events are the
source of truth in an event-sourced system. They are never deleted, never
modified, and never reinterpreted.

**Rules:**
- Past tense naming: `WorkflowExecutionStarted`, `TriggerFired`
- Immutable after creation
- Must carry all data needed to reconstruct state
- Must be versioned from day one (schema evolution via upcasters)

### Aggregate

A consistency boundary that enforces business rules and emits events.
Aggregates are the sole decision-makers. They receive commands, validate
invariants, and produce events. State is derived by replaying events.

**Rules:**
- Aggregates MUST enforce invariants - never emit events unconditionally
- State comes from replaying events, never from external queries
- One aggregate per stream
- Optimistic concurrency via expected version
- No side effects - aggregates are pure domain logic

### Command

A request for the system to do something. Commands are validated by
aggregates and may be accepted (producing events) or rejected (producing
an error). Commands are imperative: `StartExecution`, `FireTrigger`.

**Rules:**
- Commands may fail - always handle rejection
- Commands target a specific aggregate instance
- Commands carry intent, not decisions - the aggregate decides

### Stream

An ordered sequence of events for a single aggregate instance. Each
stream has a unique ID derived from the aggregate type and identity.

**Rules:**
- One stream per aggregate instance
- Events within a stream are strictly ordered
- Cross-stream ordering is NOT guaranteed
- Use `ExpectedVersion.NoStream` when creating a new stream to prevent
  duplicates

---

## Event Consumer Patterns

### Projection (Read Model)

A derived view built by replaying events. Projections transform the event
stream into a shape optimized for reading. They are disposable - delete
one and rebuild it from events.

**Rules:**
- **Projections are strictly read-only** - they build state, never cause action
- Replay 1000 times = same result, zero external calls
- No HTTP clients, no message publishing, no container launches
- No imports from infrastructure or external service modules
- Projections are rebuilt from scratch on version bump
- Must implement: `get_name()`, `get_version()`, `get_subscribed_event_types()`, `handle_event()`
- Returns `ProjectionResult` (SUCCESS / SKIP / FAILURE)

**ESP base class:** `CheckpointedProjection`

**Test:**
> Replay the entire event store from position 0 through this projection.
> Assert zero side effects, zero external calls, zero network traffic.

### Processor (To-Do List Pattern)

A component that reads pending work items and executes them. The To-Do
List pattern (Dilger, Ch. 37) splits event-driven side effects into two
parts with a hard boundary between them.

**Two parts:**
1. **Projection side** - Writes to-do records when events arrive (read-only,
   replay-safe, always runs)
2. **Processor side** - Reads pending to-do records and executes them
   (live-only, idempotent, never runs during replay)

**Rules:**
- The projection side MUST be pure (same rules as any projection)
- The processor side MUST be idempotent - same item processed twice = same result
- The processor side MUST never run during event catch-up replay
- The framework controls when the processor side executes
- On crash: processor restarts, re-reads pending items, picks up work
- Each to-do item has a stable idempotency key for dedup

**ESP base class:** `ProcessManager` (proposed - see ESP gap plan)

**Flow:**
```
Event -> Projection writes to-do record (read-only, replay-safe)
      -> Processor reads pending records (live-only, idempotent)
      -> Processor dispatches command or infrastructure call
      -> Processor marks record done
      -> On crash: restart, re-read pending, resume
```

**Why not Sagas?**
Sagas introduce compensation logic and distributed transactions. The
Processor To-Do List pattern is simpler and sufficient for our use cases.
We explicitly do NOT use sagas.

### Subscription Coordinator

The ESP component that manages event subscriptions for all projections
and process managers. It handles:
- Catch-up replay (replaying historical events to rebuild state)
- Live event dispatch (forwarding new events in real time)
- Checkpoint tracking (remembering each projection's progress)
- Version mismatch detection (triggering rebuilds when projection code changes)

**Rules:**
- The coordinator MUST distinguish between catch-up and live modes
- During catch-up, only projection-side handlers run (no side effects)
- During live processing, both projection-side and processor-side run
- Checkpoints are per-projection, durably stored

---

## Architectural Boundaries

### The Three-Way Split

Every component in the system belongs to exactly one of three concerns:

| Concern | What it does | Side effects? | Replay safe? |
|---------|-------------|--------------|-------------|
| **Observe** | Discover external facts, normalize, record | No | Yes |
| **Decide** | Evaluate rules, check guards, apply policy | No | Yes (deterministic) |
| **Execute** | Launch workflows, call LLMs, spend money | Yes (but idempotent) | Never |

**Non-negotiable:** If a single component spans two columns, that is
where bugs live. The boundary between Decide and Execute is where cost
leakage occurs.

### Bounded Context

A linguistic and organizational boundary around a cohesive set of domain
concepts. Each bounded context has its own aggregates, events, and
ubiquitous language.

**Rules:**
- No circular dependencies between contexts
- Cross-context communication via integration events only
- Each context owns its aggregates and projections
- A bounded context MUST have `aggregate_*/` folders

### Vertical Slice

A self-contained feature that cuts across all layers (domain, application,
infrastructure) for a single use case. Enforced by the VSA CLI tool.

---

## Safety Patterns

### Content-Based Dedup Key

A deterministic identifier derived from the content of an external fact,
not from delivery metadata. Two deliveries of the same logical event
produce the same dedup key regardless of source (webhook, polling, retry).

**Examples:**
- PR event: `pr:{repo_id}:{pr_number}:{action}:{sha}`
- Check run: `check_run:{repo_id}:{check_run_id}:{status}`

**Rules:**
- Dedup keys MUST be content-based, not delivery-based
- Dedup keys MUST be deterministic - same input = same key
- Dedup checks MUST be durable (database-backed, not in-memory)
- Fail-open dedup (skip check when backend is down) requires second-layer
  guards

### ExpectedVersion

Optimistic concurrency control for event streams. When appending events,
the client declares the expected current version of the stream.

| Mode | Meaning | Use case |
|------|---------|----------|
| `NoStream` | Stream must not exist yet | Creating a new aggregate (prevents duplicates) |
| `Exact(n)` | Stream must be at version n | Normal command handling |
| `Any` | No version check | Rare - only when ordering doesn't matter |

### Checkpoint

A durable record of how far a projection has processed in the event
stream. Stored per-projection in Postgres. Used by the coordinator to
resume projections after restart without replaying from the beginning.

**Rules:**
- Checkpoints MUST be stored durably (not in memory)
- Checkpoint update MUST be atomic with projection state update (for SQL-backed projections)
- On version mismatch, checkpoint is cleared and projection rebuilds from scratch

### Idempotency Key

A stable identifier for a unit of work that prevents duplicate execution.
The key is checked before work begins and recorded atomically with the
work.

**Rules:**
- Idempotency keys MUST be checked at the last gate before expensive action
- The check MUST be durable (survives restart)
- The check MUST be atomic with the action (no gap between check and do)
- "Cannot happen twice" is enforced, not assumed

---

## Anti-Patterns

### Projection with Side Effects

A projection that dispatches commands, calls external APIs, or creates
infrastructure during event handling. This is the single most dangerous
pattern in an event-sourced system because projections run during replay.

**Why it is dangerous:** On restart, version bump, or checkpoint loss,
the coordinator replays events through projections. If a projection has
side effects, every historical event re-triggers those effects.

**Fix:** Extract the side-effecting logic into a Processor (To-Do List
pattern). The projection writes to-do records. The processor executes them.

### God Service

A service class that accumulates multiple responsibilities (lifecycle
management, error handling, observability, credential management) in a
single file. Makes state machine bugs invisible because exceptions are
caught and swallowed at multiple levels.

**Fix:** Extract each responsibility into a focused handler (< 200 LOC).
Use the Processor To-Do List pattern for orchestration.

### In-Memory Lock for Correctness

Using `asyncio.Lock` or in-memory dictionaries to prevent race conditions
in business-critical paths. These are lost on restart and don't work
across multiple instances.

**Fix:** Use Postgres advisory locks or a distributed lock (Redis) for
correctness-critical mutual exclusion.

### Fail-Open Guard

A safety check that is skipped when its backing infrastructure (Redis,
Postgres) is unavailable. The system proceeds as if the check passed.

**Fix:** Fail-open is acceptable for dedup (processing twice is better
than dropping events), but MUST be paired with a durable guard at the
point of spend. Never fail-open on the last gate before money.

---

## References

- Martin Dilger, *Understanding Event Sourcing* - primary pattern reference
  - Ch. 37: Processor To-Do List pattern
- Event Modeling: https://eventmodeling.org/posts/what-is-event-modeling/
- To-Do List + Passage of Time patterns: https://event-driven.io/en/to_do_list_and_passage_of_time_patterns_combined/
- [Architectural Fitness](architectural-fitness.md) - standing fitness checklist
- [ESP Platform Philosophy](../../lib/event-sourcing-platform/docs/PLATFORM-PHILOSOPHY.md)
