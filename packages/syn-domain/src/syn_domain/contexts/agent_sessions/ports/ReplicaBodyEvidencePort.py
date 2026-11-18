"""Verified evidence of what a remote store holds for one transcript revision (#946).

A capture receipt binds the APSS original-content hash. A store that keeps the
row but empties the body still echoes that hash, and ``stored_content_hash``
is of the sanitized body, which may legitimately differ, so neither hash says
whether a body was stored. #946 measured two such rows: Codex with search text
extracted and ``raw`` empty, and Claude Code with nothing extracted but a
message count. Remote PRESENT therefore needs a read of the stored row, which
the exporter or store must supply behind this port. syn137 does not read the
store format itself.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import (
    BodyAvailability,
    InventoryModel,
)
from syn_domain.contexts.agent_sessions.ports.QualifiedSessionStorePort import (
    QualifiedSessionIdentity,  # noqa: TC001 - needed at runtime for Pydantic field validation
)


class ReplicaBodyReading(InventoryModel):
    """Sizes of the stored row, read back for one transcript revision."""

    identity: QualifiedSessionIdentity
    revision: str = Field(min_length=1)
    raw_bytes: int = Field(ge=0)
    search_text_bytes: int = Field(ge=0)
    message_count: int = Field(ge=0)


class ReplicaBodyEvidencePort(Protocol):
    async def read_body(
        self, destination_id: str, identity: QualifiedSessionIdentity, revision: str
    ) -> ReplicaBodyReading | None:
        """None only for confirmed absence of that revision at the destination."""
        ...


def replica_body_availability(
    reading: ReplicaBodyReading | None,
    identity: QualifiedSessionIdentity,
    revision: str,
    archived_bytes: int,
) -> BodyAvailability:
    """PRESENT only for a stored raw body when the archive has bytes.

    Search text and message count never stand in for the body: they are what
    both #946 signatures kept.
    """
    if reading is None:
        return BodyAvailability.MISSING
    if reading.identity != identity or reading.revision != revision:
        raise ValueError("replica body reading belongs to another transcript revision")
    if archived_bytes > 0 and reading.raw_bytes == 0:
        return BodyAvailability.MISSING
    return BodyAvailability.PRESENT
