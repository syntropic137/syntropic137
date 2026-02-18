"""WorkflowExecution aggregate - execution lifecycle.

Aggregate Root: WorkflowExecutionAggregate
Entities: PhaseExecution (has identity: phase_id)
Value Objects: ExecutionStatus, ExecutionMetrics, PhaseResult

This aggregate manages individual workflow executions:
- Start/complete/fail execution
- Phase lifecycle management
- Metrics and cost tracking
- Pause/resume/cancel control

Each execution is its own aggregate, keyed by execution_id.
Multiple concurrent executions of the same workflow are allowed.
"""

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    WorkflowExecutionAggregate,
)

__all__ = ["WorkflowExecutionAggregate"]
