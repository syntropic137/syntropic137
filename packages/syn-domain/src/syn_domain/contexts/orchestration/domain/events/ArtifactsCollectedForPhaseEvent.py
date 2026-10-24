"""ArtifactsCollectedForPhase event - outputs stored as artifacts."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event
from pydantic import Field

from syn_domain.contexts.orchestration._shared.FileRefusalValueObjects import (
    FileRefusal,  # noqa: TC001 - needed at runtime for Pydantic
)
from syn_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
    ObservedHead,  # noqa: TC001 - needed at runtime for Pydantic
)


@event("ArtifactsCollectedForPhase", "v1")
class ArtifactsCollectedForPhaseEvent(DomainEvent):
    """Event emitted when artifacts have been collected from a phase workspace.

    Records which artifact IDs were created and basic content summary.
    The actual artifact content is managed by the artifacts bounded context.
    """

    workflow_id: str
    execution_id: str
    phase_id: str
    artifact_ids: list[str]
    collected_at: datetime
    first_content_preview: str | None = None
    session_id: str | None = None

    #: True when the phase's deliverable was recovered from its transcript
    #: rather than read off disk (#1195, #1300).
    #:
    #: Recorded at the moment it is KNOWN - collection - and read back by the
    #: aggregate when the phase completes, so that `PhaseCompletedEvent` can
    #: say so without the processor holding the fact in memory across two
    #: to-do items. Carrying it in memory is the defect #1300's review found
    #: in the salvage input itself; the fix is the same one, in the same
    #: place, for the same reason.
    deliverable_recovered: bool = False

    #: The forge's heads for every branch this execution pushed, inherited or
    #: declared, read host-side during collection (plan §A.2). Recorded only.
    observed_heads: list[ObservedHead] = Field(default_factory=list)

    #: Output files the provider would not read (a link, a special file, one
    #: past a read limit), each by path and reason (#1913). The collection
    #: went on without them, so this is the only record they existed; a
    #: refused file is never stored as an empty or a missing one.
    refused_files: list[FileRefusal] = Field(default_factory=list)
