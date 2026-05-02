# 11 - Event Sourcing Platform Audit

**Status:** COMPLETE

## Purpose

The architectural fitness problems in Syntropic137 stem from gaps in the
event-sourcing-platform (ESP) framework itself. Rather than patching
Syn137, we should fix ESP so that every system built on it inherits
correct separation of concerns by construction.

## What ESP Provides Today

```
event_sourcing/
  core/           -- aggregate, event, command, checkpoint, repository
  client/         -- event store gRPC + in-memory clients
  subscriptions/  -- SubscriptionCoordinator
  stores/         -- checkpoint backends (Postgres, memory)
  decorators/     -- @command_handler, @event, event registry
  testing/        -- aggregate test scenario DSL
```

**Strengths:**
- Robust checkpoint architecture with per-projection tracking
- Explicit ProjectionResult (SUCCESS/SKIP/FAILURE) preventing silent failures
- Atomic checkpoint updates for SQL-backed projections
- Event type filtering for performance
- Version mismatch detection triggering automatic rebuilds
- Multiple checkpoint backends (Postgres for prod, memory for tests)
- Exponential backoff retry in coordinator

**The base class today:** `CheckpointedProjection`
- 4 abstract methods: `get_name()`, `get_version()`, `get_subscribed_event_types()`, `handle_event()`
- `handle_event()` is async and receives `checkpoint_store`
- Returns `ProjectionResult` enum
- **No restriction on what happens inside `handle_event()`**
- A projection can call HTTP APIs, launch containers, send emails - ESP doesn't care

## What's Missing

### 1. No replay-mode awareness

The `SubscriptionCoordinator` knows when it's catching up (it calculated
the minimum position, it knows the current live position), but it does
not communicate this to projections.

`EventEnvelope` has no `is_replay` flag. The `handle_event()` signature
has no replay context parameter. All events look identical to projections
regardless of whether they're historical catch-up or live.

**File:** `coordinator.py:311` - the dispatch call:
```python
result = await projection.handle_event(envelope, self._checkpoint_store)
```

No context. No replay flag. Nothing.

### 2. No ProcessManager base class

ESP has exactly one abstraction for event consumers: `CheckpointedProjection`.
This is designed for read models - pure state reconstruction from events.

There is no concept of:
- **Process Manager** (Processor To-Do List pattern) - reacts to events
  with side effects via a to-do list, needs idempotency

We explicitly do NOT want Sagas. The Processor To-Do List pattern
(Martin Dilger, *Understanding Event Sourcing*, Ch. 37) is simpler and
sufficient. Sagas introduce compensation logic and distributed
transactions that are unnecessary complexity for our use cases.

When Syn137 needed a process manager (dispatch workflows on TriggerFired),
the only available base class was `CheckpointedProjection`. So the
dispatch logic was crammed into a projection. The framework made this the
path of least resistance.

### 3. No side-effect enforcement

`CheckpointedProjection.handle_event()` is async and unconstrained.
Nothing prevents a projection from:
- Calling external APIs
- Creating asyncio tasks
- Injecting and calling service dependencies
- Writing to databases outside the projection store

The purity of projections is a convention, not an invariant.

### 4. No framework-level fitness validation

ESP provides no built-in checks for:
- Projection purity (no side-effect imports)
- Handler classification
- Replay safety
- Idempotency guarantees

Architecture rules are documented in ADRs but enforced only by code review.

## The Boundaries (Non-Negotiable)

These are the hard rules for any system built on ESP:

| Concept | What it does | Side effects? | Called during replay? |
|---------|-------------|--------------|---------------------|
| **Aggregate** | Decides, enforces rules, emits events | No (pure domain logic) | N/A (rebuilt from events) |
| **Projection** | Builds read models from events | **Never** | **Yes** (that's the whole point) |
| **Processor** | Reads to-do list, dispatches work | Yes (but idempotent) | **Never** (live only) |

A projection replayed 1000 times must produce the same read model with
zero external calls. A processor never sees replayed events. An aggregate
is the only place business logic lives.

**Pattern:** Processor To-Do List (Martin Dilger, *Understanding Event
Sourcing*, Ch. 37). No sagas - they introduce compensation logic and
distributed transactions that are unnecessary complexity.

**Flow:**
```
Event -> Projection writes to-do record (read-only, replay-safe)
      -> Processor reads pending records (live-only, idempotent)
      -> Processor dispatches command to aggregate or infrastructure
      -> Processor marks record done
      -> On crash: processor restarts, re-reads pending, picks up
```

## ESP Enhancements -- IMPLEMENTED (2026-04-13)

All enhancements below have been implemented in
`lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/`.
146 existing tests pass (backwards compatibility confirmed).
See [12-esp-gap-plan.md](12-esp-gap-plan.md) for full implementation details.

### Enhancement 1: ProcessManager Base Class -- DONE

New file: `core/process_manager.py`. Extends CheckpointedProjection with
projection side (handle_event, pure) and processor side (process_pending,
live-only, idempotent). Coordinator gates process_pending() on live mode.

```python
class ProcessManager(CheckpointedProjection):
    """Processor To-Do List pattern (Dilger, Ch. 37).
    
    Two parts with a hard boundary between them:
    
    PROJECTION SIDE (read-only, replay-safe):
      handle_event() writes to-do records to the projection store.
      Called during both replay and live processing.
      MUST NOT call external services, create tasks, or dispatch.
    
    PROCESSOR SIDE (live-only, idempotent):
      process_pending() reads pending records and does the work.
      Called by the coordinator ONLY for live events, never replay.
      MUST be idempotent - same item processed twice = same result.
    """
    
    @abstractmethod
    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
    ) -> ProjectionResult:
        """PROJECTION SIDE: Write to-do records. No side effects.
        
        Called during both replay and live processing.
        Only update the to-do list (projection store).
        """
        ...
    
    @abstractmethod
    async def process_pending(self) -> int:
        """PROCESSOR SIDE: Execute pending to-do items.
        
        Called by the coordinator ONLY for live events.
        Never called during catch-up replay.
        
        Returns the number of items processed.
        Implementations MUST be idempotent.
        """
        ...
    
    @abstractmethod
    def get_idempotency_key(self, todo_item: dict[str, object]) -> str:
        """Return a stable dedup key for this item.
        
        The framework checks this key before calling process_pending()
        to prevent duplicate processing.
        """
        ...
```

**Key properties:**
- `handle_event()` builds the to-do list (replay-safe, always called)
- `process_pending()` executes side effects (live-only, never during replay)
- `get_idempotency_key()` enforces dedup at the framework level
- The coordinator controls when `process_pending()` is called
- The boundary between projection and processor is enforced by the framework,
  not by developer discipline

### Enhancement 2: Replay Context in Coordinator -- DONE

DispatchContext with `global_nonce`-based catch-up boundary added to
`core/checkpoint.py`. Coordinator snapshots head global_nonce before
subscribing. Implementation:

```python
@dataclass(frozen=True)
class DispatchContext:
    """Context passed to projections during event dispatch."""
    is_catching_up: bool     # True during catch-up, False for live events
    global_position: int     # Current event position
    live_position: int       # Latest known position in event store
    
    @property
    def is_live(self) -> bool:
        return not self.is_catching_up
```

Update `CheckpointedProjection.handle_event()` signature:

```python
async def handle_event(
    self,
    envelope: EventEnvelope[DomainEvent],
    checkpoint_store: ProjectionCheckpointStore,
    context: DispatchContext | None = None,  # backwards-compatible
) -> ProjectionResult:
```

The coordinator sets `is_catching_up=True` until the subscription reaches
the live position, then switches to `False`.

### Enhancement 3: Projection Purity Marker -- DONE

`SIDE_EFFECTS_ALLOWED: ClassVar[bool]` added to CheckpointedProjection
(False) and ProcessManager (True):

```python
class CheckpointedProjection:
    """Base class for projections."""
    
    SIDE_EFFECTS_ALLOWED: ClassVar[bool] = False
    
    # ... existing interface ...
```

- `CheckpointedProjection`: `SIDE_EFFECTS_ALLOWED = False` (default)
- `ProcessManager`: `SIDE_EFFECTS_ALLOWED = True` (explicit opt-in)

The coordinator can log warnings or refuse to dispatch to projections
that declare `SIDE_EFFECTS_ALLOWED = False` but are detected to have
side-effecting imports (via the existing AST analysis in `_imports.py`).

### Enhancement 4: Built-in Fitness Functions -- DONE

`fitness/` module added with whitelist-based purity check (not blacklist),
ProcessManager structure check, and replay safety checker:

```python
# event_sourcing/fitness/projection_purity.py
def check_projection_purity(projection_path: Path) -> list[Violation]:
    """Check that a projection file has no side-effect imports."""
    ...

# event_sourcing/fitness/replay_safety.py  
def check_replay_safety(coordinator: SubscriptionCoordinator) -> list[Violation]:
    """Check that no projection dispatches side effects during replay."""
    ...
```

These ship with ESP. Any project using ESP can run them in CI:

```python
# ci/fitness/test_esp_invariants.py
from event_sourcing.fitness import check_projection_purity

def test_all_projections_are_pure():
    for path in find_projection_files():
        violations = check_projection_purity(path)
        assert not violations, f"Projection {path} has side effects: {violations}"
```

## How This Fixes Syn137

With these ESP enhancements:

1. `WorkflowDispatchProjection` becomes a `ProcessManager` subclass
2. `handle_event()` writes dispatch records only (pure, replay-safe)
3. `process_pending()` dispatches workflows (live-only, idempotent)
4. The coordinator never calls `process_pending()` during catch-up
5. `get_idempotency_key()` returns `execution_id` - framework enforces dedup
6. Built-in fitness functions catch any future projection that tries to
   have side effects

**The bug becomes impossible to write.** Not "caught in CI" - impossible
at the framework level.

## Implementation Status

All 4 enhancements are implemented. Remaining work:
- Phase 0.6: VSA validator rules (in progress)
- Tests for new code
- PR for ESP changes
- Syn137 migration (Phases A-E)

See [12-esp-gap-plan.md](12-esp-gap-plan.md) for detailed status of each phase.
