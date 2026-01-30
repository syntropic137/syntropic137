# Real-time Communication Architecture

**Last Updated:** 2026-01-26  
**Reference:** [ADR-019: WebSocket Control Plane Architecture](../adrs/ADR-019-websocket-control-plane.md)

---

## Overview

AEF provides **real-time communication** for long-running workflow executions through two mechanisms:

1. **WebSocket** - Bidirectional control plane (pause, resume, cancel)
2. **Server-Sent Events (SSE)** - Unidirectional event streaming (execution progress)

This dual-channel approach separates control signals from data streaming, following industry best practices.

---

## Architecture Overview

```mermaid
C4Container
    title Real-time Communication Architecture
    
    Container_Boundary(client, "Client Layer") {
        Container(dashboard, "Dashboard UI", "React + TypeScript", "Web application with real-time updates")
    }
    
    Container_Boundary(api, "API Layer") {
        Container(ws_endpoint, "WebSocket Endpoint", "FastAPI WebSocket", "/api/ws/control/{execution_id}")
        Container(sse_endpoint, "SSE Endpoint", "FastAPI SSE", "/api/executions/{execution_id}/stream")
        Container(rest_api, "REST API", "FastAPI", "HTTP control endpoints")
    }
    
    Container_Boundary(core, "Domain Core") {
        Container(controller, "ExecutionController", "Python", "Control signal processing")
        Container(state_machine, "State Machine", "Python", "Valid state transitions")
        Container(executor, "WorkflowExecutor", "Python", "Executes workflows")
    }
    
    Container_Boundary(state, "State Management") {
        Container(control_state, "Control State Store", "Redis/In-Memory", "Current execution states")
        Container(signal_queue, "Signal Queue", "Redis/In-Memory", "Pending control signals")
    }
    
    Rel(dashboard, ws_endpoint, "Connect via WebSocket", "Control signals bidirectional")
    Rel(dashboard, sse_endpoint, "Subscribe via SSE", "Execution events unidirectional")
    Rel(dashboard, rest_api, "HTTP POST", "Alternative control channel")
    
    Rel(ws_endpoint, controller, "Enqueue control signal")
    Rel(rest_api, controller, "Enqueue control signal")
    Rel(controller, state_machine, "Validate transition")
    Rel(controller, control_state, "Read/write state")
    Rel(controller, signal_queue, "Publish signal")
    
    Rel(executor, signal_queue, "Poll for signals at yield points")
    Rel(executor, state_machine, "Check valid transition")
    Rel(executor, sse_endpoint, "Emit execution events")
    Rel(sse_endpoint, dashboard, "Stream events", "SSE")
    
    UpdateRelStyle(dashboard, ws_endpoint, $lineColor="blue")
    UpdateRelStyle(dashboard, sse_endpoint, $lineColor="orange")
```

---

## Communication Channels

### Channel 1: WebSocket (Control Plane)

**Purpose:** Bidirectional real-time control signals

**Endpoint:** `wss://api.aef.dev/api/ws/control/{execution_id}`

**Direction:** Bidirectional (client ↔ server)

**Use Cases:**
- Pause execution at safe point
- Resume paused execution
- Cancel execution with cleanup
- Real-time state updates

**Message Format:**

Client → Server (Commands):
```json
{
  "command": "pause",
  "reason": "User requested pause",
  "timestamp": "2026-01-26T10:30:00Z"
}
```

Server → Client (State Updates):
```json
{
  "type": "state_changed",
  "execution_id": "exec_123",
  "old_state": "running",
  "new_state": "paused",
  "timestamp": "2026-01-26T10:30:01Z"
}
```

### Channel 2: Server-Sent Events (Data Plane)

**Purpose:** Unidirectional event streaming from server to client

**Endpoint:** `https://api.aef.dev/api/executions/{execution_id}/stream`

**Direction:** Unidirectional (server → client)

**Use Cases:**
- Stream execution progress
- Real-time tool execution events
- Token consumption updates
- Error notifications
- Phase completion events

**Event Format (SSE):**
```
event: tool_executed
data: {"tool": "bash", "duration_ms": 1234, "tokens": 150}

event: phase_completed
data: {"phase": "planning", "status": "success"}

event: execution_completed
data: {"status": "success", "total_tokens": 5000}
```

---

## Control Flow: WebSocket

### Connection Lifecycle

```mermaid
sequenceDiagram
    participant Client as Dashboard UI
    participant WS as WebSocket Handler
    participant Auth as Auth Middleware
    participant Controller as ExecutionController
    participant SM as StateMachine
    participant Store as Control State Store
    
    Client->>WS: Connect WebSocket<br/>wss://.../ws/control/exec_123
    WS->>Auth: Validate auth token
    Auth-->>WS: Authorized ✓
    
    WS->>Store: Get current state
    Store-->>WS: state="running"
    WS-->>Client: Connected + current state
    
    Note over Client,WS: Connection established
    
    Client->>WS: {"command": "pause"}
    WS->>Controller: handle_pause_command()
    Controller->>SM: validate_transition("running" → "paused")
    SM-->>Controller: Valid ✓
    Controller->>Store: set_state("paused")
    Controller-->>WS: State changed
    WS-->>Client: {"type": "state_changed", "new_state": "paused"}
    
    Note over Store: Executor polls state,<br/>sees "paused", enters pause loop
    
    Client->>WS: {"command": "resume"}
    WS->>Controller: handle_resume_command()
    Controller->>SM: validate_transition("paused" → "running")
    SM-->>Controller: Valid ✓
    Controller->>Store: set_state("running")
    Controller-->>WS: State changed
    WS-->>Client: {"type": "state_changed", "new_state": "running"}
    
    Client->>WS: Disconnect
    WS-->>Client: Connection closed
```

### State Machine

```mermaid
stateDiagram-v2
    [*] --> PENDING: Execution queued
    
    PENDING --> RUNNING: Start execution
    
    RUNNING --> PAUSED: Pause command<br/>(at safe point)
    RUNNING --> CANCELLED: Cancel command
    RUNNING --> COMPLETED: Task finished
    RUNNING --> FAILED: Error occurred
    
    PAUSED --> RUNNING: Resume command
    PAUSED --> CANCELLED: Cancel command
    
    COMPLETED --> [*]
    CANCELLED --> [*]
    FAILED --> [*]
    
    note right of RUNNING
        Executor checks for signals
        at yield points (after tools)
    end note
    
    note right of PAUSED
        Executor enters pause loop,
        polls for resume signal
    end note
    
    note right of CANCELLED
        Cleanup triggered,
        container destroyed
    end note
```

**Terminal States:** COMPLETED, CANCELLED, FAILED (no outgoing transitions)

---

## Data Flow: Server-Sent Events

### Event Streaming Lifecycle

```mermaid
sequenceDiagram
    participant Client as Dashboard UI
    participant SSE as SSE Handler
    participant Executor as WorkflowExecutor
    participant Agent as Claude CLI (in Docker)
    participant Collector as Event Collector
    
    Client->>SSE: GET /executions/exec_123/stream<br/>(Accept: text/event-stream)
    activate SSE
    SSE-->>Client: Connection established<br/>(Keep-alive)
    
    Note over Executor,Agent: Execution in progress
    
    Agent->>Collector: POST /events<br/>{"type": "tool_executed"}
    Collector->>Executor: Event processed
    Executor->>SSE: Emit event
    SSE-->>Client: event: tool_executed<br/>data: {...}
    
    Agent->>Collector: POST /events<br/>{"type": "tokens_used"}
    Collector->>Executor: Event processed
    Executor->>SSE: Emit event
    SSE-->>Client: event: tokens_used<br/>data: {...}
    
    Executor->>SSE: Phase completed
    SSE-->>Client: event: phase_completed<br/>data: {...}
    
    Executor->>SSE: Execution completed
    SSE-->>Client: event: execution_completed<br/>data: {...}
    
    SSE-->>Client: Connection closed
    deactivate SSE
```

### Event Types

| Event Type | Description | Frequency |
|------------|-------------|-----------|
| `execution_started` | Execution began | Once |
| `phase_started` | New phase began | Per phase |
| `tool_executed` | Agent used a tool | High |
| `tokens_used` | Token consumption | Per LLM call |
| `phase_completed` | Phase finished | Per phase |
| `error_occurred` | Error during execution | On error |
| `execution_completed` | Execution finished | Once |
| `execution_failed` | Execution failed | On failure |

---

## Alternative: HTTP REST API

For clients that can't maintain WebSocket connections, a REST API provides the same control functionality:

```http
POST /api/executions/{execution_id}/pause
POST /api/executions/{execution_id}/resume
POST /api/executions/{execution_id}/cancel
GET  /api/executions/{execution_id}/state
```

**Response:**
```json
{
  "execution_id": "exec_123",
  "state": "paused",
  "updated_at": "2026-01-26T10:30:00Z"
}
```

**Trade-offs:**
- ✅ Simpler (no connection management)
- ✅ Works through restrictive firewalls
- ❌ No real-time state updates (must poll)
- ❌ Higher latency

---

## Hexagonal Architecture

The control plane uses **ports & adapters** for clean separation:

```mermaid
flowchart TB
    subgraph api["API Adapters (Inbound Ports)"]
        ws[WebSocket Handler]
        rest[REST Handler]
    end
    
    subgraph core["Domain Core (Pure Logic)"]
        controller[ExecutionController]
        state_machine[StateMachine]
        commands[Command Types]
    end
    
    subgraph adapters["Storage Adapters (Outbound Ports)"]
        state_store[ControlStatePort]
        signal_queue[SignalQueuePort]
    end
    
    subgraph impl["Implementations"]
        mem_state[InMemoryStateAdapter]
        redis_state[RedisStateAdapter]
        mem_queue[InMemoryQueueAdapter]
        redis_queue[RedisQueueAdapter]
    end
    
    ws --> controller
    rest --> controller
    
    controller --> state_machine
    controller --> commands
    
    controller --> state_store
    controller --> signal_queue
    
    state_store -.->|dev| mem_state
    state_store -.->|prod| redis_state
    signal_queue -.->|dev| mem_queue
    signal_queue -.->|prod| redis_queue
    
    style core fill:#e3f2fd,color:#000
    style adapters fill:#fff3e0,color:#000
```

**Benefits:**
- ✅ Core logic testable without infrastructure
- ✅ Swap implementations (in-memory ↔ Redis)
- ✅ Transport-agnostic (WebSocket, REST, CLI)

---

## Executor Integration

The executor checks for control signals at **yield points**:

```python
async def execute_workflow(self, workflow: Workflow) -> Result:
    state = await self.get_state()
    
    for phase in workflow.phases:
        # Check for control signals BEFORE each phase
        await self.check_control_signals()
        
        result = await self.execute_phase(phase)
        
        for tool_result in result.tools:
            # Check for control signals AFTER each tool
            await self.check_control_signals()
            
            await self.emit_event(ToolExecuted(tool=tool_result))
    
    return result

async def check_control_signals(self):
    """Check for pause/cancel signals at safe yield points."""
    state = await self.control_state.get(self.execution_id)
    
    if state == "paused":
        # Enter pause loop until resumed
        await self.pause_loop()
    elif state == "cancelled":
        # Cleanup and exit
        raise ExecutionCancelled()
```

**Yield Points:**
- Before each workflow phase
- After each tool execution
- After each LLM call

**Why yield points?**
- ✅ Safe to pause (no partial operations)
- ✅ Clean state (can resume)
- ✅ Predictable behavior

---

## Dashboard UI Integration

```typescript
// WebSocket for control
const controlSocket = new WebSocket(`wss://api.aef.dev/ws/control/${executionId}`);

controlSocket.onmessage = (event) => {
  const message = JSON.parse(event.data);
  if (message.type === 'state_changed') {
    updateExecutionState(message.new_state);
  }
};

// Pause execution
function pauseExecution() {
  controlSocket.send(JSON.stringify({
    command: 'pause',
    reason: 'User requested'
  }));
}

// SSE for events
const eventSource = new EventSource(`/api/executions/${executionId}/stream`);

eventSource.addEventListener('tool_executed', (event) => {
  const data = JSON.parse(event.data);
  appendToolToTimeline(data);
});

eventSource.addEventListener('tokens_used', (event) => {
  const data = JSON.parse(event.data);
  updateTokenCount(data.tokens);
});
```

---

## Error Handling

### Connection Errors

```mermaid
sequenceDiagram
    participant Client
    participant WS as WebSocket
    participant Server
    
    Client->>WS: Connect
    WS-->>Client: Connected
    
    Note over WS,Server: Network interruption
    
    WS--xClient: Connection lost
    
    Client->>Client: Exponential backoff<br/>(1s, 2s, 4s, 8s...)
    
    Client->>WS: Reconnect attempt
    WS->>Server: Get current state
    Server-->>WS: state="running"
    WS-->>Client: Reconnected + state sync
    
    Note over Client: Resume from current state
```

### Command Failures

| Failure | Response | Action |
|---------|----------|--------|
| Invalid transition | `400 Bad Request` | Show error to user |
| Execution not found | `404 Not Found` | Redirect to list |
| Already terminal state | `409 Conflict` | Refresh state |
| Server error | `500 Internal Error` | Retry with backoff |

---

## Monitoring & Metrics

### WebSocket Metrics
- `websocket_connections_active` - Current open connections
- `websocket_messages_sent_total` - Messages sent to clients
- `websocket_messages_received_total` - Commands received
- `websocket_connection_duration_seconds` - Connection lifetime

### SSE Metrics
- `sse_connections_active` - Current SSE streams
- `sse_events_sent_total` - Events streamed
- `sse_connection_duration_seconds` - Stream lifetime

### Control Metrics
- `control_commands_total{command}` - Commands by type
- `control_transition_failures_total` - Invalid transitions
- `execution_pause_duration_seconds` - Time spent paused

---

## Related Documentation

- [ADR-019: WebSocket Control Plane Architecture](../adrs/ADR-019-websocket-control-plane.md)
- [Event Architecture](./event-architecture.md)
- [Infrastructure Data Flow](./infrastructure-data-flow.md)
