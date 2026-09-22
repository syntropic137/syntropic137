"""Stage complete snapshots, then publish atomically with head fencing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
    from syn_domain.contexts.agent_sessions.ports.SessionInventoryReadPort import (
        InventoryItem,
        InventorySnapshot,
        ItemKind,
    )


class InventoryPublicationConflict(Exception):
    """Another worker published first or this input watermark is stale."""


class InventoryNotFound(Exception):
    """No committed snapshot with this identity in the requested scope."""


class SessionInventoryWritePort(Protocol):
    async def stage(self, snapshot: InventorySnapshot) -> None: ...

    async def append(
        self,
        run: RunIdentity,
        snapshot_id: UUID,
        kind: ItemKind,
        start: int,
        items: tuple[InventoryItem, ...],
    ) -> None:
        """Idempotent batches. Reusing a position with different content fails."""
        ...

    async def publish(
        self, run: RunIdentity, snapshot_id: UUID, expected_head: UUID | None
    ) -> None:
        """All expected items must exist; stale workers cannot replace a head."""
        ...
