# ADR-015: Agent Session Observability Architecture

## Status

**Accepted** - 2025-12-05
**Updated:** 2025-12-09 - SSE replaced with WebSocket/RealTimeProjection (see ADR-010)
**Updated:** 2025-12-19 - Observability implementation simplified by ADR-029
**Updated:** 2026-02-19 - Git events now from real git hooks, not tool call inference (see ADR-043)

> **📝 Note (2025-12-19)**: The observability pipeline described here has been
> simplified by ADR-029 (Simplified Event System). Key changes:
> - **Storage**: Events now stored directly in `AgentEventStore` (TimescaleDB)
>   instead of through the event-sourcing platform
> - **Emission**: JSONL events from `agentic_events` hooks parsed by
>   `WorkflowExecutionEngine` and stored via `EventBuffer`
> - **Schema**: `AgentObservationEvent` in domain remains the canonical event
>   type for projections
>
> The core concepts (operation types, timeline projection) remain valid.
> See `lib/agentic-primitives/docs/adrs/029-simplified-event-system.md`.
>
> **📝 Note (2026-02-19)**: Git events (`git_commit`, `git_push`, etc.) now come
> from **real git hooks** installed globally in the workspace container, NOT from
> Claude Code `PreToolUse`/`PostToolUse` stream parsing. The hooks emit JSONL to
> **stderr**; the docker exec subprocess in `AgenticEventStreamAdapter` uses
> `stderr=STDOUT` to merge them into the stdout pipe, where `WorkflowExecutionEngine`
> reads them. Claude Code tool calls remain `tool_execution_started` /
> `tool_execution_completed` only — no git inference.
> See [ADR-043: Git Hook Event Pipeline](./ADR-043-git-hook-event-pipeline.md).

## Context

The Syn137 dashboard needs **full observability** into agent execution sessions. Currently:

1. Only **one aggregate operation** is recorded per session at completion
2. Individual tool calls were previously sent to SSE but **not persisted** as domain events
3. Session detail page shows minimal information
4. No visibility into tool inputs/outputs, messages, or thinking content

Users need to see:
- Every tool invocation (Read, Write, Bash, etc.) with inputs and outputs
- Every message request/response to/from the LLM
- Extended thinking content
- Real-time updates as operations occur
- Aggregated metrics (tool call count, message count, token usage)

## Decision Drivers

1. **Event Sourcing Native** - Leverage existing ES infrastructure
2. **Vertical Slice Architecture** - Follow established patterns
3. **Backward Compatibility** - Don't break existing event replay
4. **Performance** - Handle high event volume efficiently
5. **Real-time Updates** - WebSocket integration for live UI (via RealTimeProjection)

## Considered Options

### Option A: Fine-Grained Domain Events

Create separate event types for each activity:

```
sessions/slices/
├── record_tool_use/
│   └── ToolUseRecordedEvent
├── record_message/
│   └── MessageRecordedEvent
├── record_thinking/
│   └── ThinkingRecordedEvent
```

**Pros**: Type-safe, clear separation
**Cons**: Event type proliferation, more complex projections

### Option B: Event Metadata Enrichment

Keep single `OperationRecordedEvent` with rich metadata:

```python
@event("OperationRecorded", "v2")
class OperationRecordedEvent(DomainEvent):
    operation_type: OperationType
    metadata: dict[str, Any]  # Untyped payload
```

**Pros**: Simple, flexible
**Cons**: Untyped, "god event" anti-pattern

### Option C: Enhanced Operation Types (Selected)

Extend `OperationType` enum and add typed optional fields to existing event:

```python
class OperationType(str, Enum):
    MESSAGE_REQUEST = "message_request"
    MESSAGE_RESPONSE = "message_response"
    TOOL_EXECUTION_STARTED = "tool_started"
    TOOL_EXECUTION_COMPLETED = "tool_completed"
    TOOL_BLOCKED = "tool_blocked"
    THINKING = "thinking"
    ERROR = "error"

@event("OperationRecorded", "v2")
class OperationRecordedEvent(DomainEvent):
    operation_type: OperationType

    # Existing fields
    tool_name: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    # New typed optional fields
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None
    message_role: str | None = None
    message_content: str | None = None
    thinking_content: str | None = None
```

## Decision

**Selected: Option C - Enhanced Operation Types**

This approach:
1. Reuses existing `OperationRecordedEvent` infrastructure
2. Adds typed optional fields for different operation types
3. Maintains backward compatibility (v1 events still work)
4. Allows rich filtering by operation type
5. Follows vertical slice pattern (new command wrappers per type)

## Consequences

### Positive

- **Single event type** - Simpler projection logic
- **Typed fields** - Better than untyped metadata
- **Backward compatible** - Old events replay correctly
- **Flexible** - Easy to add new operation types
- **Queryable** - Filter by operation_type in projections

### Negative

- **Event payload size** - May grow with new fields
- **Optional field explosion** - Many nullable fields
- **Discipline required** - Must use correct fields per type

### Neutral

- **Convenience commands** - Add `RecordToolStartedCommand`, `RecordMessageCommand`, etc. as typed wrappers around `RecordOperationCommand`

## Implementation

### 1. Extend OperationType Enum

```python
# packages/syn-domain/.../value_objects.py
class OperationType(str, Enum):
    # Messages (LLM API calls)
    MESSAGE_REQUEST = "message_request"
    MESSAGE_RESPONSE = "message_response"

    # Tool lifecycle
    TOOL_EXECUTION_STARTED = "tool_started"
    TOOL_EXECUTION_COMPLETED = "tool_completed"
    TOOL_BLOCKED = "tool_blocked"

    # Extended thinking
    THINKING = "thinking"

    # Errors
    ERROR = "error"

    # Legacy (deprecated, keep for backward compat)
    AGENT_REQUEST = "agent_request"
    TOOL_EXECUTION = "tool_execution"
    VALIDATION = "validation"
```

### 2. Enhance Event Fields

```python
# packages/syn-domain/.../OperationRecordedEvent.py
@event("OperationRecorded", "v2")
class OperationRecordedEvent(DomainEvent):
    session_id: str
    operation_id: str
    operation_type: OperationType
    timestamp: datetime

    # Duration and success
    duration_seconds: float | None = None
    success: bool = True

    # Token metrics
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Tool execution (for TOOL_* types)
    tool_name: str | None = None
    tool_use_id: str | None = None
    tool_input: dict[str, Any] | None = None
    tool_output: str | None = None  # Truncated

    # Message (for MESSAGE_* types)
    message_role: str | None = None  # user, assistant, system
    message_content: str | None = None  # Truncated

    # Thinking (for THINKING type)
    thinking_content: str | None = None  # Truncated

    # Generic metadata
    metadata: dict[str, Any] = {}
```

### 3. Event Flow

The event flow differs based on agent execution pattern (see ADR-017 for details):

#### Pattern A: CLI Agent (File-based hooks)

```
Claude Code CLI
       │
       ├─► Hook Script ────► .agentic/analytics/events.jsonl
       │                              │
       │                              ▼
       │                        AnalyticsStreamer (file watcher)
       │                              │
       │                              ▼
       │                        RecordOperationCommand
       │                              │
       │                              ▼
       │                        OperationRecordedEvent
       │                              │
       │                              ▼
       │                        Event Store → Projections → UI
```

#### Pattern B: SDK Agent (Stdout - recommended for containers)

```
claude-agent-sdk query()
       │
       ├─► ResultMessage ────► AgentRunner.emit_*()
       │                              │
       │                              ▼ stdout (JSONL)
       │                        Orchestrator (reads stdout)
       │                              │
       │                              ▼
       │                        EventCollectorPort.collect_*()
       │                              │
       │                              ▼
       │                        SessionAggregate
       │                              │
       │                              ▼
       │                        OperationRecordedEvent
       │                              │
       │                              ▼
       │                        Event Store → Subscription
       │                              │
       │                              ▼
       │                        ProjectionManager
       │                              │
       │              ┌───────────────┼───────────────┐
       │              ▼               ▼               ▼
       │        Persisting      Persisting     RealTimeProjection
       │        Projections     Projections          │
       │                                             ▼
       │                                      WebSocket → UI
       │
       └─► TaskCompleted
```

**Note**: Pattern B (stdout) is the industry standard for containerized agent execution and scales to 10,000+ concurrent agents. See ADR-017 for architectural rationale.

### 4. Projection Timeline

```python
# Projection builds timeline from operations
timeline = [
    {"type": "tool_started", "tool_name": "Read", "timestamp": "..."},
    {"type": "tool_completed", "tool_name": "Read", "output": "...", "duration": 0.1},
    {"type": "message_response", "tokens": 150, "content": "..."},
    {"type": "tool_started", "tool_name": "Write", "timestamp": "..."},
    ...
]
```

## Migration

### Backward Compatibility

- Old `OperationType.AGENT_REQUEST` and `TOOL_EXECUTION` remain in enum
- Projection handles both v1 and v2 event formats
- New fields default to `None` for old events

### Data Cleanup (Optional)

No migration needed - old events work as-is. Future events get richer data.

## Related ADRs

- [ADR-008: VSA Projection Architecture](./ADR-008-vsa-projection-architecture.md)
- [ADR-009: Agentic Execution Architecture](./ADR-009-agentic-execution-architecture.md)
- [ADR-010: Event Subscription Architecture](./ADR-010-event-subscription-architecture.md)
- [ADR-013: Event Sourcing Projection Consistency](./ADR-013-event-sourcing-projection-consistency.md)
- [ADR-043: Git Hook Event Pipeline](./ADR-043-git-hook-event-pipeline.md) — how git events reach the engine via real git hooks + stderr merge

## References

- Project Plan: `PROJECT-PLAN_20251205_FULL-AGENT-OBSERVABILITY.md`
