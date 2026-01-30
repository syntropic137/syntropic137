# ADR-032: Domain Event Type Safety

**Status: ✅ ACCEPTED**

**Date:** 2025-12-17

**Deciders:** @neural

**Related:**
- ADR-031: SQL Schema Validation
- Event Sourcing Platform SDK

---

## Context

AEF uses event sourcing with a Rust-based Event Store Server. Type safety is critical because:
- Events are the source of truth for the entire system
- Type mismatches can cause data corruption or silent failures
- Python's dynamic nature means errors can slip through without proper validation

We need a comprehensive type safety strategy that catches errors as early as possible.

## Decision

We adopt a **multi-layer type safety approach** that leverages:

1. **Protobuf schemas** - Contract between Rust and Python
2. **Generated type stubs** - Enable mypy validation of gRPC calls
3. **Pydantic DomainEvent base class** - Strict validation of event payloads
4. **mypy in CI** - Catches type errors before merge

### Type Safety Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TYPE SAFETY LAYERS                            │
├──────────────────┬───────────────────┬─────────────────────────────────┤
│     LAYER        │   STATIC (mypy)   │        RUNTIME                  │
├──────────────────┼───────────────────┼─────────────────────────────────┤
│ Domain Event     │ ✅ Pydantic model │ ✅ Pydantic validation          │
│ (WorkflowCreated)│    frozen=True    │    extra="forbid"               │
├──────────────────┼───────────────────┼─────────────────────────────────┤
│ EventEnvelope    │ ✅ Generic[TEvent]│ ✅ Type tracking                │
├──────────────────┼───────────────────┼─────────────────────────────────┤
│ gRPC Transport   │ ✅ .pyi stubs     │ ✅ Protobuf serialization       │
├──────────────────┼───────────────────┼─────────────────────────────────┤
│ Rust Event Store │      N/A          │ ✅ Compile-time types           │
└──────────────────┴───────────────────┴─────────────────────────────────┘
```

### Required Patterns

#### 1. All Domain Events MUST Inherit from DomainEvent

```python
from event_sourcing import DomainEvent, event

@event("WorkflowCreated", "v1")
class WorkflowCreatedEvent(DomainEvent):
    """DomainEvent provides frozen=True, extra='forbid'."""
    workflow_id: str
    name: str
```

The `DomainEvent` base class enforces:
- `frozen=True` - Events are immutable
- `extra="forbid"` - No unknown fields allowed
- JSON serialization via Pydantic

#### 2. Use @event Decorator for Metadata

```python
@event("EventTypeName", "v1")
class MyEvent(DomainEvent):
    ...
```

This sets `event_type` and `schema_version` class variables.

#### 3. Type Annotations Required

All event fields must have type annotations:

```python
# ✅ Good
class OrderPlaced(DomainEvent):
    order_id: str
    amount: Decimal
    items: list[str]

# ❌ Bad - no type annotations
class OrderPlaced(DomainEvent):
    order_id = ""
    amount = 0
```

### Validation in CI

#### 1. mypy Type Checking (Already Enabled)

```yaml
# .github/workflows/ci.yml
- name: Type check
  run: uv run mypy apps packages
```

#### 2. Domain Event Inheritance Check (New)

A validation script ensures all event classes inherit from `DomainEvent`:

```bash
# Run as part of CI
uv run python scripts/validate_domain_events.py
```

This catches:
- Events that don't inherit from `DomainEvent`
- Events missing the `@event` decorator
- Events with `extra="allow"` (too permissive)

### What This Catches

| Error Type | When Caught | By What |
|------------|-------------|---------|
| Wrong field type | mypy time | Static analysis |
| Missing required field | mypy time | Static analysis |
| Unknown field in event | Runtime | Pydantic `extra="forbid"` |
| Mutating frozen event | Runtime | Pydantic `frozen=True` |
| Event not inheriting DomainEvent | CI | Validation script |
| Proto/Python mismatch | Runtime | Protobuf serialization |

### What This Doesn't Catch

- Business logic errors (valid types but wrong semantics)
- Events with correct structure but wrong data
- Schema version mismatches (handled by upcasters)

For these, use:
- Unit tests for business logic
- Integration tests for end-to-end flows
- Upcasters for schema evolution

## Consequences

### Positive

- Type errors caught at mypy time (before code runs)
- Runtime validation as second line of defense
- Clear error messages when validation fails
- Immutable events prevent accidental modification
- Consistent event structure across the codebase

### Negative

- Slightly more verbose event definitions
- Must regenerate stubs when proto changes
- Pydantic validation adds microseconds per event

### Future: Event Store Validation

Consider adding validation in the Rust Event Store to reject events that don't match expected schemas. This would be the ultimate backstop, catching issues even if Python validation is bypassed.

## Migration Completed

The following events were migrated from `@dataclass` to `DomainEvent`:

| Event | Location | Status |
|-------|----------|--------|
| `AppInstalledEvent` | `contexts/github/install_app/` | ✅ Done |
| `InstallationRevokedEvent` | `contexts/github/install_app/` | ✅ Done |
| `InstallationSuspendedEvent` | `contexts/github/install_app/` | ✅ Done |
| `TokenRefreshedEvent` | `contexts/github/refresh_token/` | ✅ Done |

All 32 domain events now inherit from `DomainEvent` with strict validation.

## Related: Observability Event Type Safety (ADR-038)

AEF has **two event systems** with different type safety strategies:

| Event System | Purpose | Type Safety Approach |
|--------------|---------|---------------------|
| **Domain Events** | Business state changes | Pydantic `DomainEvent` base class |
| **Observability Events** | Agent telemetry | Typed factories (`aef_shared.events.factories`) |

### Domain Events (This ADR)

```python
# Pydantic-based, immutable, schema-validated
@event("WorkflowCreated", "v1")
class WorkflowCreatedEvent(DomainEvent):
    workflow_id: str
    name: str
```

### Observability Events (ADR-038)

```python
# Factory-based, typed arguments, no magic strings
from aef_shared.events.factories import tool_started

event = tool_started(
    session_id=sid,
    tool_name="Read",
    tool_use_id="t1",
)
```

**Why different approaches?**

- **Domain events** are persisted forever, need schema versioning → Pydantic + upcasters
- **Observability events** are telemetry, need fast creation → Typed factories

Both catch schema drift at mypy time, not runtime.

## References

- `lib/event-sourcing-platform/event-sourcing/python/src/event_sourcing/core/event.py` - DomainEvent base class
- `packages/aef-domain/src/aef_domain/contexts/workflows/create_workflow/WorkflowCreatedEvent.py` - Example event
- `packages/aef-shared/src/aef_shared/events/factories.py` - Observability event factories
- `docs/adrs/ADR-038-test-organization-standard.md` - Test organization with typed factories
- `.github/workflows/ci.yml` - CI configuration with mypy
