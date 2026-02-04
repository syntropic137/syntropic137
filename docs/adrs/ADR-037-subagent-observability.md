# ADR-037: Subagent Observability

## Status

Accepted

## Date

2025-01-08

## Context

Claude CLI's `Task` tool enables spawning nested agents (subagents) to handle subtasks. These subagents run independently and can use their own tools, accumulating tokens and costs. Without proper observability, we lose visibility into:

1. **Subagent lifecycle** - When subagents start/stop
2. **Tool attribution** - Which tools were used by which subagent
3. **Cost breakdown** - Token usage per subagent
4. **Hierarchy visualization** - Parent-child relationships

The `agentic-primitives` library (v0.3.0) added subagent detection in `EventParser`, emitting `SUBAGENT_STARTED` and `SUBAGENT_STOPPED` events when the `Task` tool is used.

## Decision

Integrate subagent observability into AEF's event pipeline:

### 1. Event Types (aef-shared)

Add two new event types to `aef_shared.events`:

```python
SUBAGENT_STARTED = "subagent_started"
SUBAGENT_STOPPED = "subagent_stopped"
```

### 2. Event Flow

```
Claude CLI → Task tool → EventParser detects subagent
                              │
                              ▼
                    SUBAGENT_STARTED event
                              │
                              ▼
              WorkflowExecutionEngine records observation
                              │
                              ▼
                    EventBuffer → TimescaleDB
                              │
                              ▼
              ProjectionManager → SessionListProjection
                              │
                              ▼
                    SessionSummary.subagents updated
                              │
                              ▼
              RealTimeProjection → WebSocket → Dashboard
```

### 3. Data Model

**SubagentRecord** (in SessionSummary):

```python
@dataclass
class SubagentRecord:
    subagent_tool_use_id: str  # Correlation ID (Task tool_use_id)
    agent_name: str            # From Task input
    started_at: datetime | None
    stopped_at: datetime | None
    duration_ms: int | None
    tools_used: dict[str, int]  # {tool_name: count}
    success: bool
```

**SessionSummary additions**:

```python
subagent_count: int = 0
subagents: tuple[SubagentRecord, ...] = ()
tools_by_subagent: dict[str, dict[str, int]] = {}  # Aggregated
num_turns: int = 0
duration_api_ms: int | None = None
```

### 4. Container Runner Events

New dataclasses for streaming:

```python
@dataclass
class ContainerSubagentStarted:
    agent_name: str
    subagent_tool_use_id: str
    timestamp: datetime

@dataclass
class ContainerSubagentStopped:
    agent_name: str
    subagent_tool_use_id: str
    duration_ms: int | None
    tools_used: dict[str, int]
    success: bool
```

### 5. Dashboard UI

- `SubagentCard` component for displaying individual subagents
- `SubagentList` component for session detail page
- Event type icons/colors for `subagent_started`/`subagent_stopped`
- Real-time updates via WebSocket

## Consequences

### Positive

- **Full visibility** into nested agent execution
- **Cost attribution** per subagent for billing/optimization
- **Debugging** - trace issues to specific subagents
- **Metrics** - track subagent usage patterns
- **Real-time** - live updates as subagents spawn/complete

### Negative

- **Event volume** - More events to store/process
- **Complexity** - Additional projection logic
- **UI density** - Sessions with many subagents need careful UX

### Neutral

- Requires `agentic-primitives` v0.3.0+ for `EventParser` support
- Recording fixtures include subagent events for testing

## Implementation

### Files Changed

**aef-shared**:
- `packages/aef-shared/src/aef_shared/events/__init__.py` - Event types

**aef-adapters**:
- `packages/aef-adapters/src/aef_adapters/events/models.py` - Event mapping
- `packages/aef-adapters/src/aef_adapters/projections/manager.py` - Event routing
- `packages/aef-adapters/src/aef_adapters/projections/realtime.py` - WebSocket push

**aef-domain**:
- `packages/aef-domain/.../WorkflowExecutionEngine.py` - Subagent event detection and recording

**aef-domain**:
- `packages/aef-domain/.../session_summary.py` - SubagentRecord dataclass
- `packages/aef-domain/.../projection.py` - Subagent event handlers

**Dashboard**:
- `apps/aef-dashboard-ui/src/types/index.ts` - TypeScript types
- `apps/aef-dashboard-ui/src/components/SubagentCard.tsx` - New component
- `apps/aef-dashboard-ui/src/pages/SessionDetail.tsx` - Subagent section

### Testing

Recording-based tests using `v2.0.76_claude-haiku-4-5_subagent-concurrent.jsonl` fixture from agentic-primitives.

## References

- [agentic-primitives PR #50](https://github.com/NeuralEmpowerment/agentic-primitives/pull/50) - Subagent observability
- [ADR-015](./ADR-015-agent-observability.md) - Agent Observability
- [ADR-029](./ADR-029-ai-agent-testing-verification.md) - Recording-based testing
