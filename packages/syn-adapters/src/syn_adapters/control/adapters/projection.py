"""Projection-backed control state adapter.

Reads execution state from the projection store, which is backed by the event store.
This ensures control plane state is consistent with the actual execution state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_adapters.control.state_machine import ExecutionState

# Import projection name constant for type safety - prevents typo bugs
from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol


class ProjectionControlStateAdapter:
    """Control state adapter that reads from the projection store.

    The projection store contains execution state derived from events,
    so this ensures the control plane sees the authoritative state.
    """

    def __init__(self, projection_store: ProjectionStoreProtocol) -> None:
        self._store = projection_store

    async def save_state(self, execution_id: str, state: ExecutionState) -> None:
        """Save execution state.

        Note: In an event-sourced system, state changes should go through
        domain events. This method is a no-op as state is derived from events.
        The executor should emit state change events instead.
        """
        # State is derived from events - the executor should emit events
        # that will update the projection. This is intentionally a no-op.
        pass

    async def get_state(self, execution_id: str) -> ExecutionState | None:
        """Get current execution state from projection."""
        # Use the projection's constant for type safety
        execution = await self._store.get(
            WorkflowExecutionDetailProjection.PROJECTION_NAME, execution_id
        )

        if execution is None:
            return None

        # Map projection status to ExecutionState
        status = execution.get("status", "unknown")
        return _status_to_state(status)


def _status_to_state(status: str) -> ExecutionState:
    """Map projection status string to ExecutionState enum."""
    mapping = {
        "pending": ExecutionState.PENDING,
        "running": ExecutionState.RUNNING,
        "paused": ExecutionState.PAUSED,
        "completed": ExecutionState.COMPLETED,
        "failed": ExecutionState.FAILED,
        "cancelled": ExecutionState.CANCELLED,
        "interrupted": ExecutionState.INTERRUPTED,
    }
    return mapping.get(status.lower(), ExecutionState.FAILED)
