"""Projection for artifact list view."""

from typing import Any

from aef_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)


class ArtifactListProjection:
    """Builds artifact list read model from events.

    This projection maintains a summary view of all artifacts for
    efficient listing and filtering.
    """

    PROJECTION_NAME = "artifact_summaries"

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    @property
    def name(self) -> str:
        """Get the projection name."""
        return self.PROJECTION_NAME

    async def on_artifact_created(self, event_data: dict) -> None:
        """Handle ArtifactCreated event."""
        artifact_id = event_data.get("artifact_id", "")
        summary = ArtifactSummary(
            id=artifact_id,
            workflow_id=event_data.get("workflow_id", ""),
            session_id=event_data.get("session_id"),
            phase_id=event_data.get("phase_id"),
            artifact_type=event_data.get("artifact_type", "unknown"),
            name=event_data.get("title", "Untitled"),
            created_at=event_data.get("created_at"),
        )
        await self._store.save(self.PROJECTION_NAME, artifact_id, summary.to_dict())

    async def get_all(self) -> list[ArtifactSummary]:
        """Get all artifacts."""
        data = await self._store.get_all(self.PROJECTION_NAME)
        return [ArtifactSummary.from_dict(d) for d in data]

    async def get_by_workflow(self, workflow_id: str) -> list[ArtifactSummary]:
        """Get artifacts for a specific workflow."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"workflow_id": workflow_id},
        )
        return [ArtifactSummary.from_dict(d) for d in data]

    async def get_by_phase(self, phase_id: str) -> list[ArtifactSummary]:
        """Get artifacts for a specific phase."""
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"phase_id": phase_id},
        )
        return [ArtifactSummary.from_dict(d) for d in data]

    async def query(
        self,
        workflow_id: str | None = None,
        session_id: str | None = None,
        phase_id: str | None = None,
        artifact_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
        order_by: str = "-created_at",
    ) -> list[ArtifactSummary]:
        """Query artifacts with optional filtering."""
        filters = {}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if session_id:
            filters["session_id"] = session_id
        if phase_id:
            filters["phase_id"] = phase_id
        if artifact_type:
            filters["artifact_type"] = artifact_type

        data = await self._store.query(
            self.PROJECTION_NAME,
            filters=filters if filters else None,
            order_by=order_by,
            limit=limit,
            offset=offset,
        )
        return [ArtifactSummary.from_dict(d) for d in data]
