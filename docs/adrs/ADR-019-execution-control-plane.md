---
title: "ADR-019: Execution Control Plane Architecture"
status: accepted
created: 2024-12-09
updated: 2024-12-09
author: Agent
---

# ADR-019: Execution Control Plane Architecture

## Status

**Accepted**

- Created: 2024-12-09
- Updated: 2024-12-09
- Author(s): Agent

## Context

Agentic workflows can run for extended periods, and operators need the ability to:

1. **Pause**: Temporarily halt execution (e.g., to review progress)
2. **Resume**: Continue a paused execution
3. **Cancel**: Stop execution with cleanup
4. **Inject**: Add context or instructions during execution

Currently, once a workflow starts, there's no control mechanism. If an agent goes off-track, the only option is to kill the process, losing all context.

**Requirements:**
- Multiple clients: Web dashboard, CLI, mobile app
- Real-time feedback: State changes visible immediately
- Clean separation: Control logic independent of transport (WebSocket, HTTP)
- Testable: Domain logic testable without I/O dependencies

## Decision

We will implement a control plane using **hexagonal architecture** (ports & adapters):

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
```

**Core Components:**

1. **Commands** (`commands.py`):
   - `PauseExecution`, `ResumeExecution`, `CancelExecution`, `InjectContext`
   - Immutable dataclasses with `execution_id` and optional `reason`

2. **State Machine** (`state_machine.py`):
   - States: `PENDING`, `RUNNING`, `PAUSED`, `CANCELLED`, `COMPLETED`, `FAILED`
   - Enforces valid transitions (can't pause a completed execution)

3. **Controller** (`controller.py`):
   - Receives commands, validates against state machine
   - Queues signals for executor pickup
   - Manages state persistence via ports

4. **Ports** (`ports.py`):
   - `ControlStatePort`: Save/get execution state
   - `SignalQueuePort`: Enqueue/dequeue control signals

**Signal Flow:**
1. Client sends command (e.g., `PauseExecution`)
2. Controller validates against current state
3. Controller queues `ControlSignal` via `SignalQueuePort`
4. Executor checks for signals at yield points
5. Executor acknowledges state transition

## Alternatives Considered

### Alternative 1: Direct Process Signals (SIGSTOP/SIGCONT)

**Description**: Use OS-level signals to pause/resume processes

**Pros**:
- Immediate effect
- No application code changes needed

**Cons**:
- Not portable (different on Windows)
- Loses application state context
- Can't inject context mid-execution
- Breaks database connections, sockets

**Reason for rejection**: Too coarse-grained; breaks application state

---

### Alternative 2: Database Polling

**Description**: Executor polls database for control commands

**Pros**:
- Simple implementation
- Works across distributed systems

**Cons**:
- Latency (polling interval)
- Database load
- Not real-time

**Reason for rejection**: Need real-time responsiveness; polling adds latency

---

### Alternative 3: Direct WebSocket from Executor

**Description**: Each executor maintains its own WebSocket connection

**Pros**:
- Real-time bidirectional
- Direct control

**Cons**:
- Couples executor to transport
- Hard to test
- Doesn't support multiple client types

**Reason for rejection**: Violates hexagonal architecture; hard to test

## Consequences

### Positive Consequences

- **Testable Core**: 26 unit tests for domain logic without I/O
- **Transport Agnostic**: Add new clients (mobile, Slack) without changing core
- **Type Safety**: Commands and states are strongly typed
- **Clean Separation**: Business rules isolated from infrastructure

### Negative Consequences

- **Complexity**: More layers than direct implementation
- **Learning Curve**: Team must understand ports & adapters pattern
- **Async Coordination**: Signal queue adds eventual consistency

### Neutral Consequences

- State changes are eventually consistent (signal queue)
- Executor must cooperate by checking signals

## Implementation Notes

**Package Location:** `packages/aef-adapters/src/aef_adapters/control/`

**Files:**
- `commands.py` - `PauseExecution`, `ResumeExecution`, `CancelExecution`, `InjectContext`
- `state_machine.py` - `ExecutionStateMachine`, `ExecutionState`, `InvalidTransitionError`
- `controller.py` - `ExecutionController`
- `ports.py` - `ControlStatePort`, `SignalQueuePort` protocols
- `adapters/memory.py` - In-memory implementations for development

**Usage:**
```python
from aef_adapters.control import (
    ExecutionController,
    PauseExecution,
    ExecutionState,
)
from aef_adapters.control.adapters.memory import (
    InMemoryControlStateAdapter,
    InMemorySignalQueueAdapter,
)

# Setup
controller = ExecutionController(
    state_port=InMemoryControlStateAdapter(),
    signal_port=InMemorySignalQueueAdapter(),
)

# Initialize execution
await controller.initialize_execution("exec-123", ExecutionState.RUNNING)

# Send command
result = await controller.handle_command(
    PauseExecution(execution_id="exec-123", reason="Review progress")
)

# Executor checks for signals
signal = await controller.check_signal("exec-123")
if signal and signal.signal_type == ControlSignalType.PAUSE:
    # Handle pause
    await controller.acknowledge_state("exec-123", ExecutionState.PAUSED)
```

**Next Steps (M6-M7):**
- WebSocket adapter for dashboard
- HTTP adapter for REST API
- CLI commands (`aef control pause/resume/cancel`)

## References

- ADR-014: Workflow Execution Model - Base execution architecture
- ADR-018: Commands vs Observations - Event pattern distinction
- [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)
- [Ports & Adapters Pattern](https://herbertograca.com/2017/09/14/ports-adapters-architecture/)
- PR #10: Implementation of this ADR
