"""ExecuteWorkflow command handler — VSA compliance wrapper.

Delegates to WorkflowExecutionProcessor (ISS-196 Processor To-Do List pattern).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    AgentConfiguration,
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
        merged_inputs = self._merge_inputs(command, workflow)
        repo_url = self._resolve_repo_url(workflow, merged_inputs)

        return await self._processor.run(
            workflow_id=command.aggregate_id,
            workflow_name=workflow.name or "",
            phases=phases,
            inputs=merged_inputs,
            execution_id=command.execution_id or str(uuid4()),
            repo_url=repo_url,
        )

    @staticmethod
    def _merge_inputs(
        command: ExecuteWorkflowCommand,
        workflow: WorkflowTemplateAggregate,
    ) -> dict[str, Any]:
        """Merge input_declarations defaults and task field into command inputs."""
        merged = dict(command.inputs)
        for decl in workflow.input_declarations:
            if decl.default is not None and decl.name not in merged:
                merged[decl.name] = decl.default
        if command.task is not None:
            merged["task"] = command.task
        return merged

    @staticmethod
    def _resolve_repo_url(
        workflow: WorkflowTemplateAggregate,
        merged_inputs: dict[str, Any],
    ) -> str | None:
        """Resolve placeholders in repo_url and guard against unresolved ones."""
        repo_url: str | None = getattr(workflow, "_repository_url", None)
        if not repo_url:
            return repo_url
        for key, value in merged_inputs.items():
            repo_url = repo_url.replace(f"{{{{{key}}}}}", str(value))
        if "{{" in repo_url:
            unresolved = re.findall(r"\{\{(\w+)\}\}", repo_url)
            msg = (
                f"Repository URL contains unresolved placeholders: {unresolved}. "
                f"Provide them via inputs (e.g., --input {unresolved[0]}=<value>)."
            )
            raise ValueError(msg)
        return repo_url

    @staticmethod
    def _get_executable_phases(
        workflow: WorkflowTemplateAggregate,
    ) -> list[ExecutablePhase]:
        """Convert workflow template phases to executable phases."""
        executable_phases = []
        for phase in workflow.phases:
            phase_model = getattr(phase, "model", None)
            agent_config = (
                AgentConfiguration(model=phase_model) if phase_model else AgentConfiguration()
            )
            executable_phases.append(
                ExecutablePhase(
                    phase_id=phase.phase_id,
                    name=phase.name,
                    order=phase.order,
                    description=phase.description,
                    agent_config=agent_config,
                    prompt_template=phase.prompt_template or "",
                    output_artifact_type=(
                        phase.output_artifact_types[0] if phase.output_artifact_types else "text"
                    ),
                    timeout_seconds=phase.timeout_seconds,
                )
            )
        return executable_phases
