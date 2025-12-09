# ADR-019: WebSocket Control Plane Architecture

## Status

Accepted

## Date

2024-12-09

## Context

The Agentic Engineering Framework executes long-running workflows that can take minutes to hours to complete. During execution, users need the ability to:

1. **Pause** execution at a safe point (between tool calls)
2. **Resume** paused executions
3. **Cancel** executions with proper cleanup
4. **Inject context** into running executions (future enhancement)

These control operations need to work from multiple interfaces:
- Web dashboard (real-time updates via WebSocket)
- REST API (programmatic control)
- CLI (terminal-based control)

The control plane must be:
- **Non-blocking**: Control signals shouldn't wait for acknowledgment
- **Safe**: State transitions follow a well-defined state machine
- **Observable**: State changes are visible in real-time
- **Testable**: Core logic is independent of transport mechanisms

## Decision

We implement a **hexagonal (ports & adapters) architecture** for the control plane with the following components:

### 1. Domain Core (Pure Logic)

```
packages/aef-adapters/src/aef_adapters/control/
├── commands.py      # Command types (PauseExecution, ResumeExecution, etc.)
├── state_machine.py # ExecutionStateMachine with valid transitions
├── controller.py    # ExecutionController business logic
└── ports.py         # Abstract port definitions
```

**State Machine Transitions:**
```
PENDING → RUNNING → PAUSED → RUNNING (resume)
                  ↘ CANCELLED
        → COMPLETED
        → FAILED
```

Terminal states (CANCELLED, COMPLETED, FAILED) have no outgoing transitions.

### 2. Adapters

**Storage Adapters** (`ControlStatePort`):
- `InMemoryControlStateAdapter` - Development/testing
- Future: Redis adapter for distributed deployments

**Signal Queue Adapters** (`SignalQueuePort`):
- `InMemorySignalQueueAdapter` - Development/testing
- Future: Redis Pub/Sub for distributed signal delivery

### 3. API Adapters

**WebSocket Endpoint** (`/api/ws/control/{execution_id}`):
- Bidirectional real-time communication
- Client sends: `{"command": "pause", "reason": "..."}`
- Server sends: `{"type": "state", "state": "running"}`

**HTTP REST Endpoints**:
- `POST /api/executions/{id}/pause` - Queue pause signal
- `POST /api/executions/{id}/resume` - Queue resume signal
- `POST /api/executions/{id}/cancel` - Queue cancel signal
- `GET /api/executions/{id}/state` - Get current state

### 4. Executor Integration

The executor checks for control signals at yield points (after tool events):

```python
async for event in agent.execute(task, workspace, config):
    yield ToolUsed(...)
    
    # Check for control signals
    if self._check_signal:
        signal = await self._check_signal(ctx.execution_id)
        if signal and signal.signal_type == ControlSignalType.PAUSE:
            yield ExecutionPaused(...)
            # Wait for resume/cancel
            ...
```

New execution events:
- `ExecutionPaused` - Emitted when execution pauses
- `ExecutionResumed` - Emitted when execution resumes
- `ExecutionCancelled` - Emitted when execution is cancelled

### 5. Frontend Integration

React hook for WebSocket-based control:

```typescript
const { state, pause, resume, cancel, canPause, canResume, canCancel } = useExecutionControl(executionId)
```

### 6. CLI Integration

```bash
aef control pause <execution_id> --reason "Need to review"
aef control resume <execution_id>
aef control cancel <execution_id> --force
aef control status <execution_id>
```

## Architecture Diagram

```
                 ┌─────────────────────────────────────┐
                 │          DOMAIN CORE                │
                 │   (Pure Python, no I/O, testable)   │
                 │                                     │
                 │  commands.py    - Command types     │
                 │  state_machine.py - State logic     │
                 │  controller.py  - Business rules    │
                 │  ports.py       - Abstract ports    │
                 └─────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │ WebSocket │   │   HTTP    │   │  Memory   │
        │  Adapter  │   │  Adapter  │   │  Adapter  │
        └───────────┘   └───────────┘   └───────────┘
              │               │               │
        ┌─────▼─────┐   ┌─────▼─────┐   ┌─────▼─────┐
        │  Browser  │   │   CLI     │   │ Executor  │
        │  (React)  │   │  (Typer)  │   │  (Agent)  │
        └───────────┘   └───────────┘   └───────────┘
```

## Consequences

### Positive

1. **Clean separation of concerns** - Domain logic is testable without mocking I/O
2. **Multiple interfaces** - Same control operations available via WebSocket, HTTP, CLI
3. **Real-time updates** - WebSocket enables immediate UI feedback
4. **Safe state transitions** - State machine prevents invalid operations
5. **Graceful control** - Pauses at safe yield points, not mid-tool-execution
6. **Extensible** - Easy to add Redis adapters for distributed deployment

### Negative

1. **Additional complexity** - More components to maintain
2. **Signal latency** - Polling loop in pause state (1s intervals)
3. **Memory state** - In-memory adapters don't persist across restarts

### Neutral

1. **Hexagonal architecture** - Common pattern but requires understanding
2. **WebSocket connection management** - Need reconnection handling in UI

## Alternatives Considered

### 1. Direct Thread/Process Cancellation
- **Rejected**: Too dangerous, could leave resources in inconsistent state

### 2. Shared Database Polling
- **Rejected**: Higher latency, more database load

### 3. Message Queue (RabbitMQ/SQS)
- **Deferred**: Good for production scale, but over-engineering for initial implementation

## Implementation

Files created/modified:

```
packages/aef-adapters/src/aef_adapters/control/
├── __init__.py
├── commands.py
├── state_machine.py
├── controller.py
├── ports.py
└── adapters/
    ├── __init__.py
    └── memory.py

packages/aef-adapters/src/aef_adapters/orchestration/executor.py  # Modified

apps/aef-dashboard/src/aef_dashboard/api/control.py
apps/aef-dashboard/src/aef_dashboard/services/control.py

apps/aef-dashboard-ui/src/hooks/useExecutionControl.ts
apps/aef-dashboard-ui/src/components/ExecutionControl.tsx

apps/aef-cli/src/aef_cli/commands/control.py
```

## References

- [ADR-018: Commands vs Observations](./ADR-018-commands-vs-observations-event-architecture.md)
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
