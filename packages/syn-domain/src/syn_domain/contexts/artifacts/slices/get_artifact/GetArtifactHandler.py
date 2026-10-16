"""Find one artifact by its full id (#1570).

The read model is the fast answer, but not the authority on whether an
artifact exists: ``artifact_summaries`` is built asynchronously, so for as long
as it lags, a freshly created artifact has no row there while its
``ArtifactCreated`` event is in the event store and its bytes are in object
storage. Answering "not found" from the read model alone made that window a
404 -- recovering the artifact took a shell inside MinIO.

So a miss falls through to the aggregate, which is the truth. It carries the
``storage_uri`` its upload reported, and that is what locates the bytes: the
object key includes the workflow and execution ids, and the artifact id alone
builds a different key (#990, #1652).

Listing and search stay on the read model; only a read by id has a single
aggregate to load.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from syn_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)

if TYPE_CHECKING:
    from syn_domain.contexts.artifacts.domain.aggregate_artifact.ArtifactAggregate import (
        ArtifactAggregate,
    )
    from syn_domain.repository import Repository


class _ArtifactsById(Protocol):
    """The read model, as far as a read by id needs it."""

    async def get_by_id(self, artifact_id: str) -> ArtifactSummary | None: ...


class GetArtifactHandler:
    """One artifact by full id: the read model's row, else the aggregate's state."""

    def __init__(
        self,
        projection: _ArtifactsById,
        repository: Repository[ArtifactAggregate],
    ) -> None:
        self._projection = projection
        self._repository = repository

    async def handle(self, artifact_id: str) -> ArtifactSummary | None:
        """The artifact, or None if it was never created or has been deleted."""
        row = await self._projection.get_by_id(artifact_id)
        if row is not None:
            return row
        aggregate = await self._repository.get_by_id(artifact_id)
        if aggregate is None or aggregate.id is None or aggregate.is_deleted:
            return None
        return _summary_of(aggregate.id, aggregate)


def _summary_of(artifact_id: str, aggregate: ArtifactAggregate) -> ArtifactSummary:
    """The row ``ArtifactListProjection`` will write once it catches up."""
    return ArtifactSummary(
        id=artifact_id,
        workflow_id=aggregate.workflow_id or "",
        execution_id=aggregate.execution_id,
        session_id=aggregate.session_id,
        phase_id=aggregate.phase_id,
        artifact_type=aggregate.artifact_type.value if aggregate.artifact_type else "unknown",
        name=aggregate.title or "Untitled",
        created_at=aggregate.created_at,
        size_bytes=aggregate.size_bytes,
        content=aggregate.content,
        content_hash=aggregate.content_hash,
        content_type=aggregate.content_type.value,
        storage_uri=aggregate.storage_uri,
        is_primary_deliverable=aggregate.is_primary_deliverable,
        source_path=aggregate.source_path,
        agent_provider=aggregate.agent.provider,
        agent_model=aggregate.agent.model,
    )
