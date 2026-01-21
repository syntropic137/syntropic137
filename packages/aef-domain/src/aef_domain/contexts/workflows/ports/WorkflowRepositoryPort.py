"""Port interface for WorkflowAggregate repository.

This port defines the contract for persisting and retrieving Workflow aggregates.
Adapters in aef-adapters implement this protocol structurally (duck typing).
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aef_domain.contexts.workflows._shared import WorkflowAggregate


class WorkflowRepositoryPort(Protocol):
    """Repository port for WorkflowAggregate persistence.

    This port follows the Repository pattern from DDD. Adapters provide
    concrete implementations (e.g., EventStoreRepository, InMemoryRepository).
    """

    async def get_by_id(self, workflow_id: str) -> "WorkflowAggregate | None":
        """Retrieve workflow aggregate by ID.

        Args:
            workflow_id: The unique identifier of the workflow.

        Returns:
            WorkflowAggregate if found, None otherwise.
        """
        ...

    async def save(self, aggregate: "WorkflowAggregate") -> None:
        """Persist workflow aggregate with uncommitted events.

        This method should:
        1. Persist uncommitted events to the event store
        2. Mark events as committed on the aggregate

        Args:
            aggregate: The workflow aggregate to persist.
        """
        ...

    async def exists(self, workflow_id: str) -> bool:
        """Check if a workflow exists.

        Args:
            workflow_id: The unique identifier of the workflow.

        Returns:
            True if workflow exists, False otherwise.
        """
        ...


