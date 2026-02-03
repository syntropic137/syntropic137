"""Workflow aggregate - workflow definitions.

Aggregate Root: WorkflowAggregate
Value Objects: PhaseDefinition, WorkflowType, WorkflowClassification

This aggregate manages workflow definitions:
- Name, description, and classification
- Phases with their execution order
- Repository information

Workflows are long-lived definitions that can have multiple executions.
"""

from aef_domain.contexts.orchestration.domain.aggregate_workflow.WorkflowAggregate import (
    WorkflowAggregate,
)

__all__ = ["WorkflowAggregate"]
