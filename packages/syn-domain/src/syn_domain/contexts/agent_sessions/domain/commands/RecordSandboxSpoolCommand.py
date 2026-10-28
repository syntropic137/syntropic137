"""RecordSandboxSpool command - records the sandbox that holds a session's spool."""

from __future__ import annotations

from event_sourcing import command
from pydantic import BaseModel, ConfigDict, Field

from syn_domain.contexts.agent_sessions.domain.events.SandboxSpoolRecordedEvent import (
    RemoteSpoolBackend,  # noqa: TC001 - pydantic resolves the annotation at runtime
)


@command(
    "RecordSandboxSpool",
    "Records the remote sandbox that holds a session's capture spool",
)
class RecordSandboxSpoolCommand(BaseModel):
    """Issued once the sandbox exists, before any agent launches in it (#2161)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    aggregate_id: str = Field(..., description="Session whose spool the sandbox holds")
    backend: RemoteSpoolBackend
    executor_id: str = Field(..., min_length=1, description="syn.host_id of the creator")
    sandbox_id: str = Field(..., min_length=1, description="The provider's sandbox id")
