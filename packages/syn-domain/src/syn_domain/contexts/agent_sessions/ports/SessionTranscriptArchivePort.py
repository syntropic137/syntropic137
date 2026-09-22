"""Local, immutable transcript bytes, independent of any optional replica."""

from __future__ import annotations

from typing import Annotated, Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryModel


class ArchivedTranscript(InventoryModel):
    """Hash of exact archived bytes, distinct from APSS's envelope/content hash."""

    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    size: int = Field(ge=0)


class TranscriptIntegrityError(Exception):
    """An archive object does not match its immutable reference."""


class SessionTranscriptArchivePort(Protocol):
    async def put(self, body: bytes) -> ArchivedTranscript:
        """Acknowledge only after bytes are durable. Retrying is idempotent."""
        ...

    async def get(self, reference: ArchivedTranscript) -> bytes | None:
        """None means absent. Unavailable/corrupt storage raises, never looks absent."""
        ...
