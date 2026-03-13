"""ExecuteWorkflow command handler — VSA compliance wrapper.

Delegates to WorkflowExecutionProcessor (ISS-196 Processor To-Do List pattern).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ExecutablePhase,
)
from syn_domain.contexts.orchestration.slices.execute_workflow.errors import (
    WorkflowNotFoundError,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.ExecuteWorkflowCommand import (
        ExecuteWorkflowCommand,
    )
    from syn_domain.contexts.orchestration.slices.execute_workflow.WorkflowExecutionProcessor import (
        WorkflowExecutionProcessor,
        WorkflowExecutionResult,
    )

logger = logging.getLogger(__name__)


class WorkflowRepository(Protocol):
    """Repository protocol for Workflow aggregates."""

    async def get_by_id(self, workflow_id: str) -> WorkflowTemplateAggregate | None: ...


class ExecuteWorkflowHandler:
    """Handler for ExecuteWorkflow command (VSA compliance).

    Loads the workflow template, extracts phases, and delegates
    to WorkflowExecutionProcessor for event-driven execution.
    """

    def __init__(
        self,
        processor: WorkflowExecutionProcessor,
        workflow_repository: WorkflowRepository,
    ) -> None:
        self._processor = processor
        self._workflow_repo = workflow_repository

    async def handle(
        self,
        command: ExecuteWorkflowCommand,
    ) -> WorkflowExecutionResult:
        """Handle ExecuteWorkflow command.

        Args:
            command: ExecuteWorkflowCommand with workflow ID and inputs

        Returns:
            WorkflowExecutionResult with execution details and metrics

        Raises:
            WorkflowNotFoundError: If workflow doesn't exist
        """
        workflow = await self._workflow_repo.get_by_id(command.aggregate_id)
        if workflow is None:
            raise WorkflowNotFoundError(command.aggregate_id)

        phases = self._get_executable_phases(workflow)

        result = await self._processor.run(
            workflow_id=command.aggregate_id,
            workflow_name=workflow.name or "",
            phases=phases,
            inputs=command.inputs,
            execution_id=command.execution_id or str(uuid4()),
            repo_url=getattr(workflow, "_repository_url", None),
        )

        return result

    @staticmethod
    def _get_executable_phases(
        workflow: WorkflowTemplateAggregate,
    ) -> list[ExecutablePhase]:
        """Convert workflow template phases to executable phases."""
        executable_phases = []
        for phase in workflow.phases:
            executable_phases.append(
                ExecutablePhase(
                    phase_id=phase.phase_id,
                    name=phase.name,
                    order=phase.order,
                    description=phase.description,
                    prompt_template=phase.prompt_template or "",
                    output_artifact_type=(
                        phase.output_artifact_types[0] if phase.output_artifact_types else "text"
                    ),
                    timeout_seconds=phase.timeout_seconds,
                )
            )
        return executable_phases
