# ADR-019: WebSocket Control Plane Architecture

## Status

Accepted — **Updated 2026-03-21**

> **ISS-262 note:** The bidirectional WebSocket control endpoint (`/ws/control/{execution_id}`) was removed. It was redundant - all control actions are fully covered by the HTTP POST endpoints described in this ADR, which remain the canonical interfaces. Observation streams (execution events) are now served via SSE; see ADR-049.

> **2026-09-29 note:** Pause and resume were DELETED from the orchestration
> context. Neither was ever wired: no executor read the `pause` signal, so the
> endpoint returned 200 and the run continued, and zero `ExecutionPaused`
> events exist in 26,917. `cancel` already expresses "stop this run", and
> `ExecutionStatus.PAUSED` is gone with them. The control plane now carries
> `cancel` and `inject` only. The word `resume` was reassigned: it means
> restarting a FAILED or INTERRUPTED execution from its first incomplete
> phase, in a new execution (see the orchestration ubiquitous language).

## Date

2024-12-09

## Context

The Syntropic137 executes long-running workflows that can take minutes to hours to complete. During execution, users need the ability to:

1. **Cancel** executions with proper cleanup
2. **Inject context** into running executions (future enhancement)

Pause and resume were also listed here originally; both were deleted in 2026-09
as described in the note above.

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
packages/syn-adapters/src/syn_adapters/control/
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

**Storage Adapters** (`ControlStatePort`) - **REMOVED 2026-09-26.**

There is no control-state port. Admission is decided by
`WorkflowExecutionAggregate.accepts_control`, on the aggregate rehydrated per
request, which is the same method the aggregate's own pause/resume/cancel
handlers guard with.

The port existed so the controller could answer from stored state, and the
production adapter read the execution detail projection. A projection lags the
stream, so an execution the aggregate had already cancelled could still read
`running` and a request the aggregate would refuse was admitted, reported as
success, and queued (ADR-014 section 7, fail-open 1).

Two rules over one concept is the defect, not the lag. The controller no
longer receives a projection at all, so there is nothing left to be stale
about. `ControlStatePort`, `InMemoryControlStateAdapter`,
`ProjectionControlStateAdapter` and the duplicate state machine are deleted.

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
syn control pause <execution_id> --reason "Need to review"
syn control resume <execution_id>
syn control cancel <execution_id> --force
syn control status <execution_id>
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
packages/syn-adapters/src/syn_adapters/control/
├── __init__.py
├── commands.py
├── state_machine.py
├── controller.py
├── ports.py
└── adapters/
    ├── __init__.py
    └── memory.py

packages/syn-adapters/src/syn_adapters/orchestration/executor.py  # Modified

apps/syn-dashboard/src/syn_dashboard/api/control.py
apps/syn-dashboard/src/syn_dashboard/services/control.py

apps/syn-dashboard-ui/src/hooks/useExecutionControl.ts
apps/syn-dashboard-ui/src/components/ExecutionControl.tsx

apps/syn-cli/src/syn_cli/commands/control.py
```

## References

- [ADR-018: Commands vs Observations](./ADR-018-commands-vs-observations-event-architecture.md)
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
