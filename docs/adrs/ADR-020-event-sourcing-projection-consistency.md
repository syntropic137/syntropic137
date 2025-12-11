# ADR-020: Event Sourcing Projection Consistency

## Status
Accepted

## Date
2025-12-04

## Context

We discovered a class of bugs where:
1. Domain events were defined but never emitted by commands
2. Events were emitted but not handled by projections
3. Projection state didn't correctly reflect event data

Specifically:
- `PhaseCompleted` events were defined but never emitted during workflow execution
- Operations weren't being stored in session projections
- Workflow status was inconsistent between list and detail views

These bugs were hard to detect because:
- The code compiled without errors
- Unit tests for individual components passed
- The gaps only became visible during E2E testing

## Decision

### 1. Event Emission Completeness

**Every state change must emit a domain event.** The execution service must emit events for:
- `WorkflowExecutionStarted` - when workflow starts
- `PhaseCompleted` - when each phase completes (with metrics!)
- `WorkflowCompleted` - when workflow finishes
- `WorkflowFailed` - when workflow fails
- `SessionStarted` - when session starts
- `OperationRecorded` - when operations occur
- `SessionCompleted` - when session completes

### 2. Projection Handler Completeness

**Every domain event must have corresponding projection handlers.** Required handlers:

```
WorkflowDetailProjection:
├── on_workflow_created
├── on_workflow_execution_started
├── on_phase_started
├── on_phase_completed  ← CRITICAL: Updates phase metrics!
├── on_workflow_completed
└── on_workflow_failed

SessionListProjection:
├── on_session_started
├── on_operation_recorded  ← CRITICAL: Stores operations!
└── on_session_completed
```

### 3. Regression Test Strategy

Create integration tests that verify:
1. **Command → Event**: Each command emits the expected event
2. **Event → Projection**: Each event type has a projection handler
3. **Handler Completeness**: Projections have handlers for all required events

```python
# Example regression test
def test_workflow_detail_projection_has_required_handlers():
    required = [
        "on_workflow_created",
        "on_phase_completed",  # CRITICAL
        "on_workflow_completed",
    ]
    for handler in required:
        assert hasattr(WorkflowDetailProjection, handler)
```

### 4. Architectural Invariants

1. **No silent failures**: If a command is executed, it MUST emit events
2. **No orphan events**: Every emitted event MUST be handled by projections
3. **Data consistency**: Projection state MUST reflect all processed events
4. **Status synchronization**: List and detail views MUST show consistent status

## Consequences

### Positive
- Regression tests catch missing event handlers before deployment
- Clear documentation of which events exist and where they're handled
- Consistent data across all views (list, detail, metrics)

### Negative
- More boilerplate code for event emission
- Need to maintain regression tests as events evolve
- Slightly increased complexity in execution service

### Neutral
- Follows existing event sourcing patterns
- Aligns with DDD principles of explicit domain events

## Compliance

To maintain compliance:

1. **When adding a new event type:**
   - Add regression test for command → event emission
   - Add regression test verifying projection handlers exist
   - Update this ADR's handler completeness section

2. **When modifying projections:**
   - Run regression tests to ensure all handlers still exist
   - Verify projection state reflects new event structure

3. **During code review:**
   - Check that any new command emits appropriate events
   - Check that any new event has projection handlers

## Related ADRs
- ADR-012: Artifact Storage (event store integration)
- ADR-014: Workflow Execution Model

## Files Changed
- `packages/aef-domain/tests/integration/test_event_projection_consistency.py` - Regression tests
- `apps/aef-dashboard/src/aef_dashboard/services/execution.py` - Added `_complete_phase()`
- `packages/aef-domain/.../WorkflowExecutionAggregate.py` - Added `CompletePhaseCommand`


