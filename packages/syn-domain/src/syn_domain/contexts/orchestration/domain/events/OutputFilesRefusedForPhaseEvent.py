"""OutputFilesRefusedForPhase event - an unfinished phase's output was refused (#1913)."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event

from syn_domain.contexts.orchestration._shared.FileRefusalValueObjects import (
    FileRefusal,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("OutputFilesRefusedForPhase", "v1")
class OutputFilesRefusedForPhaseEvent(DomainEvent):
    """The provider would not read some of a phase's output when it was kept.

    A phase that will not complete (failed, cancelled, interrupted) has what it
    wrote kept before its workspace goes, and that collection does not end in
    `ArtifactsCollectedForPhase`. This is where its refusals are recorded, so
    they reach the execution on that path as they do on the completed one,
    each by path and reason, and survive a replay.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    refused_files: list[FileRefusal]
    refused_at: datetime
