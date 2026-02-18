"""Workflow aggregate - workflow definitions.

Aggregate Root: WorkflowTemplateAggregate
Value Objects: PhaseDefinition, WorkflowType, WorkflowClassification

This aggregate manages workflow definitions:
- Name, description, and classification
- Phases with their execution order
- Repository information

Workflows are long-lived definitions that can have multiple executions.
"""

from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
    WorkflowTemplateAggregate,
)

__all__ = ["WorkflowTemplateAggregate"]
