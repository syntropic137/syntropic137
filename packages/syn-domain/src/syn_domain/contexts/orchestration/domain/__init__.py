"""Domain layer for orchestration bounded context.

This module exports the aggregate roots and shared domain objects.

Aggregates (each in its own aggregate_* folder):
- WorkspaceAggregate: Isolated workspace lifecycle
- WorkflowTemplateAggregate: Workflow definition
- WorkflowExecutionAggregate: Execution lifecycle with phases

Per ADR-020:
- Each aggregate_* folder contains exactly ONE *Aggregate.py (the root)
- Entities and value objects are co-located with their aggregate
- Commands and events live in shared commands/ and events/ folders
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate as WorkflowExecutionAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate as WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
        WorkspaceAggregate as WorkspaceAggregate,
    )

__all__ = [
    "HandlerResult",
    "WorkflowExecutionAggregate",
    "WorkflowTemplateAggregate",
    "WorkspaceAggregate",
]


@dataclass(frozen=True)
class HandlerResult:
    """Discriminated result for manage handlers.

    Handlers return:
    - ``HandlerResult(success=True)`` on success
    - ``None`` when the aggregate is not found
    - ``HandlerResult(success=False, error=...)`` when a domain rule is violated
    """

    success: bool
    error: str = ""


def __getattr__(name: str) -> type:
    """Lazy import aggregates to avoid circular import issues during transition."""
    if name == "WorkspaceAggregate":
        from syn_domain.contexts.orchestration.domain.aggregate_workspace.WorkspaceAggregate import (
            WorkspaceAggregate,
        )

        return WorkspaceAggregate
    elif name == "WorkflowTemplateAggregate":
        from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
            WorkflowTemplateAggregate,
        )

        return WorkflowTemplateAggregate
    elif name == "WorkflowExecutionAggregate":
        from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            WorkflowExecutionAggregate,
        )

        return WorkflowExecutionAggregate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
