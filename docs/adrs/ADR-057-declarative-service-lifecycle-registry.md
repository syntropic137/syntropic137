# ADR-057: Declarative Service Lifecycle Registry

- **Status:** Accepted
- **Date:** 2026-04-06
- **Context:** #596 (conversations metadata null due to unregistered service)

## Problem

The API lifecycle manages several degradable services (artifact storage, subscriptions, event poller). Before this ADR, registering a service required synchronized changes in **three disconnected places**:

1. `DegradedReason` enum value
2. `_RECOVERABLE_REASONS` frozenset membership
3. `_try_recover_reason()` if/elif dispatch

Plus each service had paired `_init_*()` and `_try_recover_*()` functions that duplicated initialization logic.

This scattered registration pattern caused #596: conversation storage was wired in `_wiring.py` but never registered in `lifecycle.py`. The service initialized lazily on first request, and when initialization failed (DB unreachable), the pool stayed `None` with no recovery path. All metadata queries silently returned `None`.

## Decision

Introduce a declarative service registry in `lifecycle.py` where each degradable service is declared exactly once via a `_ServiceEntry` dataclass. The startup loop, recovery loop, and shutdown sequence all iterate this registry.

### Data Structure

```python
@dataclass(frozen=True)
class _ServiceEntry:
    reason: DegradedReason          # Enum value for health/API responses
    init_fn: Callable[[LifecycleState], Awaitable[None]]  # Raises on failure
    recoverable: bool = False       # Whether recovery loop should retry
    shutdown_fn: Callable[[LifecycleState], Awaitable[None]] | None = None
```

### Registry

```python
_SERVICE_REGISTRY: tuple[_ServiceEntry, ...] = (
    _ServiceEntry(reason=DegradedReason.ARTIFACT_STORAGE, ...),
    _ServiceEntry(reason=DegradedReason.CONVERSATION_STORAGE, ...),
    _ServiceEntry(reason=DegradedReason.SUBSCRIPTION_COORDINATOR, ...),
    _ServiceEntry(reason=DegradedReason.EVENT_POLLER, ...),
)
```

### Adding a New Service

1. Add a value to `DegradedReason`
2. Write an `_init_<service>(state: LifecycleState) -> None` function that **raises on failure**
3. Optionally write a `_shutdown_<service>(state: LifecycleState) -> None` function
4. Add a `_ServiceEntry` to `_SERVICE_REGISTRY`

No other bookkeeping is needed. Recovery, health checks, and shutdown ordering are all derived from the registry.

### What Changed

| Before | After |
|---|---|
| `_RECOVERABLE_REASONS` frozenset | Derived from `entry.recoverable` |
| `_try_recover_reason()` if/elif chain | Loop: find entry by reason, call `entry.init_fn` |
| Separate `_try_recover_*()` functions | Deleted — `init_fn` is reused for recovery |
| Manual shutdown if-chain | Loop `_SERVICE_REGISTRY` in reverse |
| Conversation storage not registered | Registered as degraded + recoverable |

### What Stays the Same

- **Event store** remains outside the registry. It's the only CRITICAL service (aborts startup) and uses a different error contract (`Result` return vs raising).
- **Credential validation** remains outside the registry. It's sync and config-based, not a service with a pool.
- **`DegradedReason` enum** is preserved for API health response serialization.
- **Recovery loop** semantics are unchanged (exponential backoff, 10s to 60s).

## Consequences

### Positive

- **Poka-yoke:** Forgetting to register a service means it doesn't start at all (fail-loud), rather than silently operating with `None` pools (fail-silent).
- **Single source of truth:** One `_ServiceEntry` per service instead of three synchronized locations.
- **DRY:** Recovery reuses `init_fn` instead of duplicating logic in `_try_recover_*` functions.
- **Ordered shutdown:** Services shut down in reverse registration order automatically.

### Negative

- All `_init_*` functions must follow the same contract (take `LifecycleState`, raise on failure). Functions that previously caught their own exceptions were refactored.
- The `_init_artifact_storage` function takes a `state` parameter it doesn't use, for uniform signature.

## Related

- #596 — Immediate bug this fixes
- #605 — Broader logging/error-handling unification (separate effort)
- ADR-011 — Structured logging standard
