"""Projection for artifact list view.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from typing import Any

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)


class ArtifactListProjection(AutoDispatchProjection):
    """Builds artifact list read model from events.

    This projection maintains a summary view of all artifacts for
    efficient listing and filtering.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.

    Version History:
        v1: Initial schema
        v2: Added size_bytes and content fields
        v3: Added execution_id for workflow execution linking (ADR-012)
    """

    PROJECTION_NAME = "artifact_summaries"
    VERSION = 3  # Added execution_id field

    def __init__(self, store: Any):  # Using Any to avoid circular import
        """Initialize with a projection store.

        Args:
            store: A ProjectionStoreProtocol implementation
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version - increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def on_artifact_created(self, event_data: dict) -> None:
        """Handle ArtifactCreated event."""
        artifact_id = event_data.get("artifact_id", "")
        content = event_data.get("content", "")
        size_bytes = event_data.get("size_bytes", 0)

        # If size_bytes not provided, calculate from content
        if not size_bytes and content:
            size_bytes = len(content.encode("utf-8")) if isinstance(content, str) else len(content)

        summary = ArtifactSummary(
            id=artifact_id,
            workflow_id=event_data.get("workflow_id", ""),
            execution_id=event_data.get("execution_id"),  # v3: Link to execution
            session_id=event_data.get("session_id"),
            phase_id=event_data.get("phase_id"),
            artifact_type=event_data.get("artifact_type", "unknown"),
            name=event_data.get("title", "Untitled"),
            created_at=event_data.get("created_at"),
            size_bytes=size_bytes,
            content=content,
            content_hash=event_data.get("content_hash"),
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

    async def get_by_execution(self, execution_id: str) -> list[ArtifactSummary]:
        """Get all artifacts for a specific execution run.

        This is the primary query for retrieving phase outputs
        to inject into subsequent phases.

        Args:
            execution_id: The workflow execution ID

        Returns:
            List of artifacts created during this execution
        """
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"execution_id": execution_id},
        )
        return [ArtifactSummary.from_dict(d) for d in data]

    async def get_by_execution_and_phase(
        self,
        execution_id: str,
        phase_id: str,
    ) -> list[ArtifactSummary]:
        """Get artifacts for a specific execution and phase.

        Args:
            execution_id: The workflow execution ID
            phase_id: The phase ID

        Returns:
            List of artifacts from the specified phase
        """
        data = await self._store.query(
            self.PROJECTION_NAME,
            filters={"execution_id": execution_id, "phase_id": phase_id},
        )
        return [ArtifactSummary.from_dict(d) for d in data]

    async def on_artifact_updated(self, event_data: dict) -> None:
        """Handle ArtifactUpdated event."""
        artifact_id = event_data.get("artifact_id", "")
        if not artifact_id:
            return
        data = await self._store.get(self.PROJECTION_NAME, artifact_id)
        if data is None:
            return
        if event_data.get("title") is not None:
            data["name"] = event_data["title"]
        if event_data.get("is_primary_deliverable") is not None:
            data["is_primary_deliverable"] = event_data["is_primary_deliverable"]
        if event_data.get("metadata") is not None:
            data["metadata"] = event_data["metadata"]
        await self._store.save(self.PROJECTION_NAME, artifact_id, data)

    async def on_artifact_deleted(self, event_data: dict) -> None:
        """Handle ArtifactDeleted event."""
        artifact_id = event_data.get("artifact_id", "")
        if not artifact_id:
            return
        await self._store.delete(self.PROJECTION_NAME, artifact_id)

    async def query(
        self,
        workflow_id: str | None = None,
        execution_id: str | None = None,
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
        if execution_id:
            filters["execution_id"] = execution_id
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
