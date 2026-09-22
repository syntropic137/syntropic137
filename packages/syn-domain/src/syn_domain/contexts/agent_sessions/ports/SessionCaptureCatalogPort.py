"""Durable acquisition metadata for replayable archive delivery and backfill."""

from typing import Literal, Protocol

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    Identifier,
    InventoryModel,
    RoutingIdentifier,
    RunIdentity,
)

from .QualifiedSessionStorePort import QualifiedSessionIdentity
from .SessionTranscriptArchivePort import ArchivedTranscript


class CataloguedCapture(InventoryModel):
    run: RunIdentity
    producer_id: RoutingIdentifier
    capture_id: RoutingIdentifier
    harness: Identifier
    native_id: Identifier | None
    content_format: Literal["native", "envelope"]
    archive: ArchivedTranscript


class SessionCaptureCatalogPort(Protocol):
    async def record(self, capture: CataloguedCapture) -> None:
        """Durably record an immutable acquisition; conflicting retries fail."""
        ...

    async def get(
        self, run: RunIdentity, producer_id: str, capture_id: str
    ) -> CataloguedCapture | None:
        """Read an acquisition only within its recorded run; this is not authorization."""
        ...

    async def get_revision(
        self, run: RunIdentity, identity: QualifiedSessionIdentity, archive_hash: str
    ) -> CataloguedCapture | None:
        """Resolve exact archived bytes, never substitute the latest captured revision."""
        ...
