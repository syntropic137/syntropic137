"""ArchiveWorkflowTemplate handler - thin application service adapter.

Checks for active executions (cross-aggregate guard) before dispatching
the archive command to the WorkflowTemplateAggregate. The guard is decided
from the template's own stream and the execution aggregates, not from a read
model; ``_shared.template_launch`` explains why that closes the race (#1588).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ConcurrencyConflictError

from syn_domain.contexts.orchestration._shared.template_launch import (
    ExecutionLookup,
    active_launches,
)
from syn_domain.contexts.orchestration.domain import HandlerResult

if TYPE_CHECKING:
    from collections.abc import Sequence

    from event_sourcing import EventEnvelope

    from syn_domain.contexts.orchestration.domain.aggregate_workflow_template.WorkflowTemplateAggregate import (
        WorkflowTemplateAggregate,
    )
    from syn_domain.contexts.orchestration.domain.commands.ArchiveWorkflowTemplateCommand import (
        ArchiveWorkflowTemplateCommand,
    )
    from syn_domain.contexts.orchestration.domain.events.WorkflowTemplateArchivedEvent import (
        WorkflowTemplateArchivedEvent,
    )
    from syn_domain.repository import Repository

logger = logging.getLogger(__name__)

# Execution statuses that indicate an active (in-progress) execution
_ACTIVE_STATUSES = frozenset({"running", "not_started"})


class _ExecutionSummary(Protocol):
    """Minimal protocol for execution summary objects used in the archive guard."""

    @property
    def workflow_execution_id(self) -> str: ...

    @property
    def status(self) -> str: ...


class ExecutionProjection(Protocol):
    """Protocol for querying executions by workflow ID.

    Consulted only for executions launched before launches were recorded on
    the template's stream (#1588): those were projected long ago. Every newer
    one is asked of its own aggregate.
    """

    async def get_by_workflow_id(self, workflow_id: str) -> Sequence[_ExecutionSummary]:
        """Return execution summaries for the given workflow."""
        ...


class EventPublisher(Protocol):
    """Protocol for publishing domain events."""

    async def publish(self, events: list[EventEnvelope[WorkflowTemplateArchivedEvent]]) -> None:
        """Publish domain events for integration."""
        ...


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
        repository: Repository[WorkflowTemplateAggregate],
        execution_projection: ExecutionProjection,
        executions: ExecutionLookup,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._repository = repository
        self._execution_projection = execution_projection
        self._executions = executions
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
        active = await self._active_executions(aggregate)
        if active:
            msg = f"Cannot archive: {active} active execution(s) in progress"
            return HandlerResult(success=False, error=msg)

        try:
            aggregate.archive_workflow(command)
        except ValueError as e:
            return HandlerResult(success=False, error=str(e))

        # Get events before save (save may mark as committed)
        events = aggregate.get_uncommitted_events()

        # A conflict here is a launch recorded since the guard read the stream.
        # Refuse rather than retry: the caller re-asks and the guard sees it.
        try:
            await self._repository.save(aggregate)
        except ConcurrencyConflictError:
            msg = "Cannot archive: an execution was launched while archiving; retry"
            return HandlerResult(success=False, error=msg)

        # Publish events for integration with projections
        if self._event_publisher and events:
            await self._event_publisher.publish(events)  # type: ignore[arg-type]

        aggregate.mark_events_as_committed()

        logger.info("Archived workflow template %s", command.workflow_id)
        return HandlerResult(success=True)

    async def _active_executions(self, aggregate: WorkflowTemplateAggregate) -> int:
        recorded = await active_launches(aggregate, self._executions, datetime.now(UTC))
        launched = aggregate.launches
        legacy = [
            e
            for e in await self._execution_projection.get_by_workflow_id(str(aggregate.id))
            if e.status in _ACTIVE_STATUSES and e.workflow_execution_id not in launched
        ]
        return len(recorded) + len(legacy)
