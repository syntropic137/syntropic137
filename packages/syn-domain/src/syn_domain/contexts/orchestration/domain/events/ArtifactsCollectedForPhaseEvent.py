"""ArtifactsCollectedForPhase event - outputs stored as artifacts."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - needed at runtime for Pydantic

from event_sourcing import DomainEvent, event


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
