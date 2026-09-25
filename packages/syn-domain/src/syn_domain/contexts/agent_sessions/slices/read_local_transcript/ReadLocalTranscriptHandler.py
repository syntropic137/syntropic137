"""Read exact local revisions only after current whole-object authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import RunIdentity
    from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
        QualifiedSessionIdentity,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionCaptureCatalogPort import (
        CataloguedCapture,
        SessionCaptureCatalogPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptAccessPort import (
        SessionTranscriptAccessPort,
    )
    from syn_domain.contexts.agent_sessions.ports.SessionTranscriptArchivePort import (
        SessionTranscriptArchivePort,
    )


@dataclass(frozen=True)
class LocalTranscriptRead:
    status: Literal["present", "not_captured", "missing", "expired", "deleted", "too_large"]
    capture: CataloguedCapture | None = None
    body: bytes | None = field(default=None, repr=False)


class ReadLocalTranscriptHandler:
    def __init__(
        self,
        catalog: SessionCaptureCatalogPort,
        archive: SessionTranscriptArchivePort,
        access: SessionTranscriptAccessPort,
        *,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("transcript read bound must be positive")
        self._catalog = catalog
        self._archive = archive
        self._access = access
        self._max_bytes = max_bytes

    async def handle(
        self, run: RunIdentity, identity: QualifiedSessionIdentity, archive_hash: str
    ) -> LocalTranscriptRead:
        capture = await self._catalog.get_revision(run, identity, archive_hash)
        if capture is None:
            return LocalTranscriptRead(status="not_captured")
        await self._access.require_read(capture)
        # A durable tombstone wins over bytes that a pending deletion has not
        # removed yet; the body is never served once removal was requested.
        tombstone = await self._access.tombstone(capture)
        if tombstone is not None:
            return LocalTranscriptRead(status=tombstone, capture=capture)
        if capture.archive.size > self._max_bytes:
            return LocalTranscriptRead(status="too_large", capture=capture)
        # Integrity and storage errors propagate; neither means confirmed absence.
        body = await self._archive.get(capture.archive)
        if body is None:
            # A deletion request marks the archive before its SQL tombstone
            # commits; ask again so the absence is labelled by its cause.
            tombstone = await self._access.tombstone(capture)
            if tombstone is not None:
                return LocalTranscriptRead(status=tombstone, capture=capture)
            deleted = await self._archive.is_deleted(capture.archive)
            return LocalTranscriptRead(status="expired" if deleted else "missing", capture=capture)
        return LocalTranscriptRead(status="present", capture=capture, body=body)
