# ADR-027: Unified Workflow Executor Architecture

**Status:** Accepted
**Date:** 2025-12-17
**Deciders:** Architecture Team
**Context:** M8 - Unified Executor Architecture

## Context

We discovered that the AEF platform had **two separate executor implementations** with inconsistent observability wiring:

1. **WorkflowExecutionEngine** (syn-domain) - Used by CLI, has event sourcing and `observability_writer`
2. **AgenticWorkflowExecutor** (syn-adapters) - Used by Dashboard, has `collector_url` (but wasn't being passed)

This caused a critical bug: **Dashboard runs had no observability data in TimescaleDB** while CLI runs worked correctly. The root cause was that `ExecutionService` was creating `AgenticWorkflowExecutor` without the `collector_url` parameter.

### Problem Statement

```
CLI Run:
  WorkflowExecutionEngine → observability_writer → TimescaleDB ✅

Dashboard Run:
  AgenticWorkflowExecutor → (no collector_url) → ❌ No TimescaleDB data
```

This violated our core principle: **"Observability is not optional - this system is useless as a black box."**

## Decision

We implemented the **Poka-Yoke pattern** (mistake-proofing) by:

1. **Creating `ObservabilityPort` protocol** in `agentic-primitives` - the interface all observability implementations must follow
2. **Creating unified `WorkflowExecutor`** that **REQUIRES** `ObservabilityPort` in its constructor (not optional!)
3. **Creating `create_workflow_executor()` factory** that auto-wires `TimescaleObservability`
4. **Adding `NullObservability`** with safety guard that throws if used outside test environment

### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     agentic-primitives                          │
├─────────────────────────────────────────────────────────────────┤
│  agentic_observability                                          │
│   ├── ObservabilityPort (Protocol)                              │
│   ├── ObservationType (Enum)                                    │
│   ├── ObservationContext (Dataclass)                            │
│   ├── NullObservability (Test only, throws if not test env)     │
│   └── TestOnlyAdapterError                                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ implements
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       syn-adapters                               │
├─────────────────────────────────────────────────────────────────┤
│  syn_adapters.observability                                      │
│   ├── TimescaleObservability (wraps ObservabilityWriter)        │
│   └── get_observability() → ObservabilityPort                   │
│                                                                  │
│  syn_adapters.orchestration                                      │
│   ├── WorkflowExecutor(__init__(observability: ObservabilityPort))
│   └── create_workflow_executor() → WorkflowExecutor             │
└─────────────────────────────────────────────────────────────────┘
```

## Poka-Yoke Guarantees

1. **Constructor requires ObservabilityPort** - `WorkflowExecutor(observability=None)` raises `TypeError`
2. **NullObservability throws outside tests** - `NullObservability()` raises `TestOnlyAdapterError` if `SYN_ENVIRONMENT != 'test'`
3. **Factory is the recommended entry point** - `create_workflow_executor()` handles DI wiring automatically
4. **Single code path** - Both CLI and Dashboard now use the same executor (or will after migration)

## Consequences

### Positive

- **Impossible to forget observability** - Constructor enforces it
- **Consistent telemetry** - All execution paths use the same ObservabilityPort
- **Testable** - NullObservability enables fast unit tests with assertion helpers
- **Type-safe** - Protocol is `@runtime_checkable`
- **Extensible** - Easy to add OpenTelemetry implementation later

### Negative

- **Migration required** - Legacy executors need to be replaced (in progress)
- **Slight overhead** - Extra abstraction layer (negligible in practice)

### Neutral

- **Two patterns coexist temporarily** - CLI still uses WorkflowExecutionEngine during migration

## Implementation

### Files Created

```
lib/agentic-primitives/lib/python/agentic_observability/
├── agentic_observability/
│   ├── __init__.py          # Exports
│   ├── protocol.py          # ObservabilityPort, ObservationType, ObservationContext
│   ├── null.py              # NullObservability with safety guard
│   └── exceptions.py        # TestOnlyAdapterError
├── tests/                   # 31 tests
├── pyproject.toml
└── README.md

packages/syn-adapters/src/syn_adapters/observability/
├── __init__.py
├── timescale.py             # TimescaleObservability
└── factory.py               # get_observability()

packages/syn-adapters/src/syn_adapters/orchestration/
├── workflow_executor.py     # WorkflowExecutor (unified)
└── factory.py               # create_workflow_executor() [updated]
```

### Usage Example

```python
# Production (Dashboard/CLI)
from syn_adapters.orchestration import create_workflow_executor

executor = create_workflow_executor(
    workspace_service=WorkspaceService.create_docker(),
)

async for event in executor.execute(workflow, inputs):
    handle_event(event)

# Tests
import os
os.environ["SYN_ENVIRONMENT"] = "test"

from agentic_observability import NullObservability

observability = NullObservability()
executor = WorkflowExecutor(
    observability=observability,
    agent_factory=mock_factory,
    workspace_service=mock_service,
)

# After test
assert observability.has_observation(ObservationType.TOOL_COMPLETED)
```

## Related ADRs

- ADR-018: Commands vs Observations Event Architecture
- ADR-026: TimescaleDB for Observability Storage
- ADR-012: Artifact Storage (Two-tier pattern)

## References

- [Poka-Yoke (Mistake-Proofing)](https://en.wikipedia.org/wiki/Poka-yoke)
- PROJECT-PLAN_20251216_AGENTIC-PRIMITIVES-EVOLUTION.md - M8: Unified Executor Architecture
