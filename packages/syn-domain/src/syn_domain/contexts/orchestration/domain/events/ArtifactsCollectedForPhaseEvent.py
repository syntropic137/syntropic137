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
