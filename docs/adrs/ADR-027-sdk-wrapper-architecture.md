# ADR-027: SDK Wrapper Architecture via agentic-primitives

**Status:** ⚠️ SUPERSEDED by ADR-029 (Simplified Event System)
**Date:** 2025-12-16
**Superseded:** 2025-12-19
**Authors:** @neural
**Related:** ADR-013 (Testing), ADR-018 (Observability Events), agentic-primitives/ADR-006 (Middleware Hooks)

> **⚠️ Superseded**: This ADR described wrapping the `claude-agent-sdk` with
> `agentic-primitives` abstractions. ADR-029 simplified this by:
> 1. Running Claude CLI directly in containers (no SDK wrapper needed)
> 2. Using `agentic_events` JSONL hooks for observability
> 3. Storing events directly in TimescaleDB via `AgentEventStore`
>
> The `syn-agent-runner` package referenced here has been deleted.
> See `lib/agentic-primitives/docs/adrs/029-simplified-event-system.md`.

## Context

### The Problem: Duplicated SDK Integration

Currently, `syn-agent-runner` implements its own Claude SDK integration with:
- Custom tool parsing from `AssistantMessage.content`
- Custom event emission via `emit_tool_use()`, `emit_token_usage()`
- Custom hooks configuration in `hooks.py`

Meanwhile, `agentic-primitives` provides a **clean, tested SDK wrapper**:
- `InstrumentedAgent`: SDK wrapper with metrics collection
- `HookClient`: Async batching with pluggable backends
- `HookEvent`: Canonical event schema
- `EventType`: Standardized event types

This duplication creates:
1. **Maintenance burden** - Two codebases to update for SDK changes
2. **Inconsistent behavior** - Different parsing logic, different event schemas
3. **Testing complexity** - Can't reuse mock fixtures
4. **Integration friction** - syn-agent-runner events don't match agentic-primitives schema

### The Vision: Clean Electrical Cabinet

Like organized wiring in an electrical cabinet:
- **Single entry points** - One place to configure SDK integration
- **Dependency injection** - Backends are pluggable (JSONL, HTTP, TimescaleDB)
- **Isolation** - Components testable in isolation
- **Observability** - All events flow through canonical schema

## Decision

Adopt `agentic-primitives` as the **canonical SDK integration layer**:

### 1. Use `HookClient` for Event Emission

```python
# BEFORE: syn-agent-runner/events.py (custom)
def emit_tool_use(tool_name: str, tool_input: dict, tool_use_id: str):
    print(json.dumps({"type": "tool_use", ...}))

# AFTER: Use agentic_hooks
from agentic_hooks import HookClient, HookEvent, EventType

client = HookClient(backend=TimescaleDBBackend())  # DI!
await client.emit(HookEvent(
    event_type=EventType.TOOL_EXECUTION_STARTED,
    session_id=session_id,
    data={"tool_name": tool_name, ...}
))
```

### 2. Extend `InstrumentedAgent` for Syn137 Specifics

```python
# packages/syn-agent-runner/src/syn_agent_runner/agent.py
from agentic_primitives.examples.claude_sdk.agent import InstrumentedAgent

class Syn137Agent(InstrumentedAgent):
    """Syn137-specific agent with TimescaleDB observability."""

    def __init__(
        self,
        hook_client: HookClient,  # DI: Injected backend
        workspace_id: str,
        **kwargs
    ):
        super().__init__(**kwargs)
        self._hook_client = hook_client
        self._workspace_id = workspace_id

    async def _on_tool_started(self, block: ToolUseBlock):
        """Override to emit via HookClient."""
        await self._hook_client.emit(HookEvent(
            event_type=EventType.TOOL_EXECUTION_STARTED,
            session_id=self.session_id,
            data={
                "tool_name": block.name,
                "tool_input": block.input,
                "workspace_id": self._workspace_id,
            }
        ))
```

### 3. Create TimescaleDB Backend for agentic_hooks

```python
# packages/syn-adapters/src/syn_adapters/observability/timescale_backend.py
from agentic_hooks.backends import Backend
from agentic_hooks.events import HookEvent

class TimescaleDBBackend(Backend):
    """agentic_hooks backend that writes to TimescaleDB."""

    def __init__(self, writer: ObservabilityWriter):
        self._writer = writer

    async def write(self, events: list[HookEvent]) -> None:
        for event in events:
            await self._writer.record_observation(
                session_id=event.session_id,
                observation_type=event.event_type.value,
                data=event.data,
            )
```

### 4. Architecture Diagram

```
┌────────────────────────────────────────────────────────────────────┐
│                         syn-agent-runner                           │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                      Syn137Agent                                │  │
│  │           (extends InstrumentedAgent)                        │  │
│  │                         │                                    │  │
│  │            ┌────────────┴────────────┐                       │  │
│  │            ▼                         ▼                       │  │
│  │   ┌──────────────┐         ┌──────────────────┐              │  │
│  │   │ HookClient   │         │ MetricsCollector │              │  │
│  │   │ (agentic-p)  │         │   (agentic-p)    │              │  │
│  │   └──────┬───────┘         └────────┬─────────┘              │  │
│  └──────────┼──────────────────────────┼────────────────────────┘  │
│             │ DI                       │ DI                        │
│             ▼                          ▼                           │
│   ┌─────────────────┐       ┌───────────────────┐                  │
│   │ TimescaleDB     │       │ JSONL Backend     │                  │
│   │ Backend         │       │ (stdout → sidecar)│                  │
│   └────────┬────────┘       └─────────┬─────────┘                  │
└────────────┼──────────────────────────┼────────────────────────────┘
             │                          │
             ▼                          ▼
      ┌──────────────┐          ┌───────────────┐
      │ TimescaleDB  │          │ Collector     │
      │ (syn-infra)  │          │ (sidecar)     │
      └──────────────┘          └───────────────┘
```

## Implementation Plan

### Phase 1: Add agentic-primitives Dependency (5 min)
```toml
# packages/syn-agent-runner/pyproject.toml
dependencies = [
    "agentic-hooks>=0.1.0",  # From lib/agentic-primitives
]
```

### Phase 2: Create TimescaleDB Backend (30 min)
- Implement `TimescaleDBBackend` in `syn-adapters`
- Tests with mock writer

### Phase 3: Refactor AgentRunner to Use Primitives (1h)
- Replace custom event emission with `HookClient`
- Replace tool parsing with `InstrumentedAgent` pattern
- Keep Syn137-specific additions (workspace_id, phase_id)

### Phase 4: Wire Dashboard API (30 min)
- Dashboard queries same `HookEvent` schema from TimescaleDB
- Consistent types end-to-end

### Phase 5: Deprecate Custom Events (cleanup)
- Remove `events.py` custom functions
- Remove duplicated parsing logic
- Update tests to use agentic-primitives mocks

## Consequences

### Positive
- **Single source of truth** - SDK integration lives in agentic-primitives
- **Consistent schema** - `HookEvent` used everywhere
- **Testable** - Reuse mock fixtures from agentic-primitives
- **Scalable** - Batching, retry logic already implemented
- **Extensible** - Easy to add new backends (e.g., OpenTelemetry)

### Negative
- **Migration effort** - Refactoring existing code
- **Dependency** - syn-agent-runner depends on agentic-primitives
- **Versioning** - Need to keep primitives in sync

### Neutral
- **Performance** - Batching might slightly delay event emission
- **Complexity** - More layers but cleaner separation

## References

- `lib/agentic-primitives/lib/python/agentic_hooks/` - Hook client library
- `lib/agentic-primitives/examples/001-claude-agent-sdk-integration/` - SDK wrapper example
- ADR-018: Commands vs Observations Event Architecture
- ADR-026: TimescaleDB for Observability Storage
