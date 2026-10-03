"""Read pricing transcripts within a verified source and harness namespace."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import model_validator

from syn_domain.contexts.agent_sessions.domain.read_models.session_inventory import InventoryNodeRef

if TYPE_CHECKING:
    from syn_domain.contexts.agent_sessions.delegate_usage import StoredSession


class QualifiedSessionIdentity(InventoryNodeRef):
    @model_validator(mode="after")
    def _transcript_only(self) -> QualifiedSessionIdentity:
        if self.kind != "transcript":
            raise ValueError("qualified session identity must identify a native transcript")
        return self


@runtime_checkable
class QualifiedSessionStorePort(Protocol):
    async def fetch_qualified_session(
        self, identity: QualifiedSessionIdentity
    ) -> StoredSession | None:
        """None only for confirmed absence; preserve the returned native ID."""
        ...
