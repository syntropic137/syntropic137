"""Port interface for WorkflowExecutionAggregate repository.

This port is REQUIRED per ADR-023: Workspace-First Execution Model.
All execution events MUST be persisted via this repository.
"""

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syn_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )


class WorkflowExecutionRepositoryPort(Protocol):
    """Repository port for WorkflowExecution aggregates.

    Required per ADR-023: Workspace-First Execution Model.
    All execution events MUST be persisted via this repository.

    This is the primary mechanism for event sourcing workflow executions.
    """

    # The identifier below is positional-only. The implementation is the generic
    # RepositoryAdapter[TAggregate], which necessarily names it aggregate_id, and
    # Protocol matching compares parameter NAMES for anything not positional-only
    # -- so a domain-specific name here would leave this port unsatisfiable (#1305).
    async def get_by_id(self, execution_id: str, /) -> "WorkflowExecutionAggregate | None":
        """Retrieve execution aggregate by ID.

        Args:
            execution_id: The unique identifier of the execution.

        Returns:
            WorkflowExecutionAggregate if found, None otherwise.
        """
        ...

    async def save(self, aggregate: "WorkflowExecutionAggregate") -> None:
        """Save the aggregate and persist uncommitted events to event store.

        This method should:
        1. Persist uncommitted events (WorkflowExecutionStarted, PhaseStarted, etc.)
        2. Mark events as committed on the aggregate
        3. Update any projections subscribed to these events

        Args:
            aggregate: The workflow execution aggregate to persist.
        """
        ...

    async def exists(self, execution_id: str, /) -> bool:
        """Check if an execution exists.

        Args:
            execution_id: The unique identifier of the execution.

        Returns:
            True if execution exists, False otherwise.
        """
        ...
