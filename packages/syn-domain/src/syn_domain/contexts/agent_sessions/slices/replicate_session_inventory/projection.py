"""Replay-pure subscription; live delivery supervision belongs to an adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from event_sourcing import ProcessManager, ProjectionCheckpoint, ProjectionResult

from syn_domain.contexts.agent_sessions.domain.events.InventoryReconciliationSweepEvent import (
    InventoryReconciliationSweepEvent,
)

if TYPE_CHECKING:
    from event_sourcing import (
        DispatchContext,
        DomainEvent,
        EventEnvelope,
        ProjectionCheckpointStore,
    )


class InventoryReplicationDispatchPort(Protocol):
    async def process_pending(self) -> int: ...
    async def stop(self) -> None: ...


class InventoryReplicationProcessManager(ProcessManager):
    PROJECTION_NAME = "session_inventory_replication"
    VERSION = 1

    def __init__(self, dispatcher: InventoryReplicationDispatchPort) -> None:
        self._dispatcher = dispatcher

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    def get_subscribed_event_types(self) -> set[str]:
        return {InventoryReconciliationSweepEvent.event_type}

    def get_idempotency_key(self, todo_item: object) -> str:
        if not isinstance(todo_item, str) or not todo_item:
            raise TypeError("replication work requires its durable operation identity")
        return todo_item

    async def handle_event(
        self,
        envelope: EventEnvelope[DomainEvent],
        checkpoint_store: ProjectionCheckpointStore,
        context: DispatchContext | None = None,  # noqa: ARG002
    ) -> ProjectionResult:
        # Published snapshot metadata already persists the to-do source. Replay
        # advances only this subscription checkpoint, never launches exporters.
        await checkpoint_store.save_checkpoint(
            ProjectionCheckpoint(
                projection_name=self.PROJECTION_NAME,
                global_position=envelope.metadata.global_nonce or 0,
                updated_at=datetime.now(UTC),
                version=self.VERSION,
            )
        )
        return ProjectionResult.SUCCESS

    async def process_pending(self) -> int:
        return await self._dispatcher.process_pending()

    async def stop(self) -> None:
        await self._dispatcher.stop()
