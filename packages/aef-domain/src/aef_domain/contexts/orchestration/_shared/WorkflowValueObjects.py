"""Value objects for the orchestration bounded context.

Compatibility re-exports from the canonical location in aggregate_workflow.
This module exists for backward compatibility with code that imported from _shared.
"""

from aef_domain.contexts.orchestration.domain.aggregate_workflow_template.value_objects import (
    PhaseDefinition,
    PhaseExecutionType,
    WorkflowClassification,
    WorkflowType,
)

__all__ = [
    "PhaseDefinition",
    "PhaseExecutionType",
    "WorkflowClassification",
    "WorkflowType",
]
