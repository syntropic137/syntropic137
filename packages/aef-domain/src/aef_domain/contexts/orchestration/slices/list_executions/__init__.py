"""List Executions slice - query for workflow execution runs."""

from aef_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)

__all__ = ["WorkflowExecutionListProjection"]
