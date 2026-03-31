"""ArchiveWorkflowTemplate handler - thin application service adapter.

Checks for active executions (cross-aggregate guard) before dispatching
the archive command to the WorkflowTemplateAggregate.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from syn_domain.contexts.orchestration.domain import HandlerResult

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
        ArchiveWorkflowTemplateCommand,
    )

logger = logging.getLogger(__name__)

# Execution statuses that indicate an active (in-progress) execution
_ACTIVE_STATUSES = frozenset({"running", "paused", "not_started"})


class ArchiveWorkflowTemplateHandler:
    """Application service handler for ArchiveWorkflowTemplateCommand.

    This handler:
    1. Loads the aggregate from the repository
    2. Checks for active executions (cross-aggregate guard)
    3. Dispatches the command to the aggregate
    4. Persists the aggregate
    5. Publishes events for integration (if publisher provided)
    """

    def __init__(
        self,
        repository: Any,
        execution_projection: Any,
        event_publisher: Any = None,
    ) -> None:
        self._repository = repository
        self._execution_projection = execution_projection
        self._event_publisher = event_publisher

    async def handle(self, command: ArchiveWorkflowTemplateCommand) -> HandlerResult | None:
        """Handle the ArchiveWorkflowTemplateCommand.

        Returns:
            HandlerResult(success=True) on success.
            HandlerResult(success=False, error=...) on domain rule violation.
            None if the aggregate is not found.
        """
        aggregate = await self._repository.get_by_id(command.workflow_id)
        if aggregate is None:
            logger.warning("Workflow template not found: %s", command.workflow_id)
            return None

        # Cross-aggregate guard: check for active executions
        executions = await self._execution_projection.get_by_workflow_id(command.workflow_id)
        active = [e for e in executions if e.status in _ACTIVE_STATUSES]
        if active:
            msg = f"Cannot archive: {len(active)} active execution(s) in progress"
            return HandlerResult(success=False, error=msg)

        try:
            aggregate.archive_workflow(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))

        # Get events before save (save may mark as committed)
        events = aggregate.get_uncommitted_events()

        await self._repository.save(aggregate)

        # Publish events for integration with projections
        if self._event_publisher and events:
            await self._event_publisher.publish(events)  # type: ignore[arg-type]

        aggregate.mark_events_as_committed()

        logger.info("Archived workflow template %s", command.workflow_id)
        return HandlerResult(success=True)
