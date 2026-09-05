"""Projection for artifact list view.

Uses CheckpointedProjection (ADR-014) for reliable position tracking.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 - runtime annotation on page()
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Collection

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
    read_primary_flag,
)
from syn_domain.pagination import (
    Page,
    ProjectionRecord,
    matches_search,
    paginate,
    within_window,
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
        v4: Added source_path so a phase can be handed the producing phase's
            whole output tree at its original relative paths (issue #988).
            Rebuilding is safe: pre-v5 ArtifactCreated events carry no
            source_path and simply project as None.
    """

    PROJECTION_NAME = "artifact_summaries"
    VERSION = 5  # Added is_primary_deliverable to the read model (#997)

    def __init__(self, store: Any):  # Using Any to avoid circular import  # noqa: ANN401
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation
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
            source_path=event_data.get("source_path"),  # v5 event field (#988)
            # Without this the flag the collector writes never reaches the
            # read model, and the cold path silently falls back to row
            # order -- the exact divergence #997 exists to close.
            is_primary_deliverable=read_primary_flag(event_data.get("is_primary_deliverable")),
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

    async def get_by_id(self, artifact_id: str) -> ArtifactSummary | None:
        """One artifact by its full id, or None.

        The caller used to be ``query(limit=10000)`` followed by a linear scan,
        which read every artifact ever written in order to return one and then
        stopped finding anything at all past the ten-thousandth row -- the same
        "a cap decides what exists" defect as the unpaged list (#1204), on the
        path the issue names as the only remaining way to reach an old
        artifact. The store indexes by key; ask it.
        """
        data = await self._store.get(self.PROJECTION_NAME, artifact_id)
        return ArtifactSummary.from_dict(data) if data else None

    async def page(
        self,
        *,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        session_id: str | None = None,
        phase_id: str | None = None,
        artifact_types: Collection[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int | None = None,
    ) -> Page[ArtifactSummary]:
        """One page of artifacts, with the total and type facets it came from.

        ``query`` answers only "which rows", which was all the endpoint asked
        for while it had no paging: it took a ``limit`` capped at 200 and
        offered no offset, so 200 artifacts were addressable and every older
        one was reachable only by an id learned somewhere else (#1204). A
        client could not even tell: a bare array of 50 looks the same whether
        50 or 5000 exist.

        ``artifact_type`` is this collection's facet dimension -- the field the
        list surface narrows by -- so it is passed as ``paginate``'s status
        dimension rather than as another equality filter. That is what makes
        the tally and the row filter read the same field by construction, and
        it is why the type counts describe every type the rest of the query
        matched instead of only the one already selected.

        Only the equality filters the store can express are pushed down. The
        window and the search cannot be, so they are spelled once here, in the
        same pass that produces ``total`` -- deriving the count separately is
        how a total comes to describe a different collection than the rows
        (#1119).

        ``search`` matches case-insensitively against the artifact id, its
        name, and the workflow and phase it belongs to.
        """
        filters = {
            key: value
            for key, value in (
                ("workflow_id", workflow_id),
                ("execution_id", execution_id),
                ("session_id", session_id),
                ("phase_id", phase_id),
            )
            if value
        }

        def base(record: ProjectionRecord) -> bool:
            return within_window(
                record.get("created_at"), created_after, created_before
            ) and matches_search(
                search,
                record.get("id"),
                record.get("name"),
                record.get("workflow_id"),
                record.get("phase_id"),
            )

        return paginate(
            await self._store.query(
                self.PROJECTION_NAME,
                filters=filters if filters else None,
                order_by="-created_at",
                limit=None,
                offset=0,
            ),
            base_predicate=base,
            status_of=lambda r: str(r.get("artifact_type") or ""),
            statuses=artifact_types,
            sort_key=lambda r: str(r.get("created_at") or ""),
            to_row=ArtifactSummary.from_dict,
            offset=offset,
            limit=limit,
        )
