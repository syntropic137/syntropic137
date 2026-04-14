"""Workflow Dispatch Projection.

Subscribes to TriggerFired events and dispatches workflow executions
via the ExecutionService.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from event_sourcing.core.checkpoint import DispatchContext

    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import (
    CheckpointedProjection,
    DomainEvent,
    EventEnvelope,
    ProjectionCheckpoint,
    ProjectionCheckpointStore,
    ProjectionResult,
)

from syn_domain.contexts.github._shared.projection_names import WORKFLOW_DISPATCH


class _ExecutionService(Protocol):
    """Protocol for the execution service dependency."""

    async def run_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, str],
        execution_id: str,
        task: str | None = None,
    ) -> None: ...


logger = logging.getLogger(__name__)

# Event types this projection subscribes to
_SUBSCRIBED_EVENTS = {
    "github.TriggerFired",
}


def _to_str_dict(value: object) -> dict[str, str]:
    """Convert an arbitrary dict-like object to dict[str, str] by stringifying values."""
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


class WorkflowDispatchProjection(CheckpointedProjection):
    """Dispatches workflow executions when triggers fire.

    This projection:
    1. Subscribes to TriggerFired events
    2. Extracts workflow_id and workflow_inputs from the event
    3. Calls ExecutionService.run_workflow() to dispatch
    4. Saves checkpoint for reliable position tracking
    """

    PROJECTION_NAME = WORKFLOW_DISPATCH
    VERSION = 1

    def __init__(
        self,
        execution_service: _ExecutionService | None = None,
        store: ProjectionStoreProtocol | None = None,
    ) -> None:
        self._execution_service = execution_service
        self._store = store

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str] | None:
        return _SUBSCRIBED_EVENTS

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        _context: DispatchContext | None = None,
    ) -> ProjectionResult:
        event_type = envelope.metadata.event_type or "Unknown"
        event_data = envelope.event.model_dump()
        global_nonce = envelope.metadata.global_nonce or 0

        try:
            if event_type == "github.TriggerFired":
                await self._on_trigger_fired(event_data)

            await checkpoint_store.save_checkpoint(
                ProjectionCheckpoint(
                    projection_name=self.PROJECTION_NAME,
                    global_position=global_nonce,
                    updated_at=datetime.now(UTC),
                    version=self.VERSION,
                )
            )
            return ProjectionResult.SUCCESS

        except Exception:
            logger.exception(
                "Error dispatching workflow",
                extra={"event_type": event_type},
            )
            return ProjectionResult.FAILURE

    async def clear_all_data(self) -> None:
        if self._store is not None:
            records = await self._store.get_all(self.PROJECTION_NAME)
            for record in records:
                key = record.get("execution_id")
                if key:
                    await self._store.delete(self.PROJECTION_NAME, key)

    async def _on_trigger_fired(self, event_data: dict[str, object]) -> None:
        """Handle a TriggerFired event by dispatching the workflow."""
        workflow_id = str(event_data.get("workflow_id", ""))
        str_inputs = _to_str_dict(event_data.get("workflow_inputs", {}))
        execution_id = str(event_data.get("execution_id", ""))
        trigger_id = event_data.get("trigger_id", "")

        dispatch_record = {
            "trigger_id": trigger_id,
            "execution_id": execution_id,
            "workflow_id": workflow_id,
            "workflow_inputs": str_inputs,
            "dispatched_at": datetime.now(UTC).isoformat(),
        }
        if self._store is not None and execution_id:
            await self._store.save(self.PROJECTION_NAME, execution_id, dispatch_record)

        if not workflow_id:
            logger.warning(f"TriggerFired event {trigger_id} has no workflow_id, skipping dispatch")
            return

        if self._execution_service is not None:
            try:
                await self._execution_service.run_workflow(
                    workflow_id=workflow_id,
                    inputs=str_inputs,
                    execution_id=execution_id,
                )
                logger.info(
                    f"Dispatched workflow {workflow_id} for trigger {trigger_id} "
                    f"-> execution {execution_id}"
                )
            except Exception:
                logger.exception(
                    f"Failed to dispatch workflow {workflow_id} for trigger {trigger_id}"
                )
                raise
        else:
            logger.info(
                f"Recorded TriggerFired dispatch: trigger={trigger_id} "
                f"workflow={workflow_id} execution={execution_id} "
                "(no execution service configured)"
            )
