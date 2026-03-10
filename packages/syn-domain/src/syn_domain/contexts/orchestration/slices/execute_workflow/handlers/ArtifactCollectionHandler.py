"""ArtifactCollectionHandler — gathers outputs, creates artifact aggregates (ISS-196).

Extracted from WorkflowExecutionEngine artifact collection (lines 1017-1036).

Reports ArtifactsCollectedCommand to the aggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
    ArtifactsCollectedCommand,
)

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.slices.execute_workflow.ArtifactCollector import (
        ArtifactCollector,
    )
    from syn_domain.contexts.orchestration.slices.execution_todo.value_objects import (
        TodoItem,
    )

logger = logging.getLogger(__name__)


class ArtifactCollectionResult:
    """Result of artifact collection."""

    __slots__ = ("artifact_ids", "command", "first_content")

    def __init__(
        self,
        artifact_ids: list[str],
        first_content: str | None,
        command: ArtifactsCollectedCommand,
    ) -> None:
        self.artifact_ids = artifact_ids
        self.first_content = first_content
        self.command = command


class ArtifactCollectionHandler:
    """Gathers outputs from workspace, creates artifact aggregates.

    Reports ArtifactsCollectedCommand.
    """

    def __init__(self, artifact_collector: ArtifactCollector) -> None:
        self._collector = artifact_collector

    async def handle(
        self,
        todo: TodoItem,
        workspace: Any,
        workflow_id: str,
        session_id: str,
        phase_name: str,
        output_artifact_type: str,
    ) -> ArtifactCollectionResult:
        """Collect artifacts from workspace after agent execution.

        Args:
            todo: The to-do item being processed
            workspace: Active workspace with file access
            workflow_id: Workflow ID
            session_id: Session ID
            phase_name: Phase name for artifact metadata
            output_artifact_type: Type of output artifact

        Returns:
            ArtifactCollectionResult with artifact IDs and aggregate command
        """
        assert todo.phase_id is not None

        collected = await self._collector.collect_from_workspace(
            workspace=workspace,
            workflow_id=workflow_id,
            phase_id=todo.phase_id,
            execution_id=todo.execution_id,
            session_id=session_id,
            phase_name=phase_name,
            output_artifact_type=output_artifact_type,
        )

        command = ArtifactsCollectedCommand(
            execution_id=todo.execution_id,
            phase_id=todo.phase_id,
            artifact_ids=collected.artifact_ids,
            first_content_preview=collected.first_content[:500]
            if collected.first_content
            else None,
        )

        return ArtifactCollectionResult(
            artifact_ids=collected.artifact_ids,
            first_content=collected.first_content,
            command=command,
        )
