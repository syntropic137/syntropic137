"""Handler for list_artifacts query."""

from aef_domain.contexts.artifacts.domain.queries.list_artifacts import (
    ListArtifactsQuery,
)
from aef_domain.contexts.artifacts.domain.read_models.artifact_summary import (
    ArtifactSummary,
)

from .projection import ArtifactListProjection


class ListArtifactsHandler:
    """Query Handler for list_artifacts.

    This handler retrieves data from the ArtifactListProjection.
    """

    def __init__(self, projection: ArtifactListProjection):
        self.projection = projection

    async def handle(self, query: ListArtifactsQuery) -> list[ArtifactSummary]:
        """Handle ListArtifactsQuery."""
        return await self.projection.query(
            workflow_id=query.workflow_id,
            session_id=query.session_id,
            phase_id=query.phase_id,
            artifact_type=query.artifact_type_filter,
            limit=query.limit,
            offset=query.offset,
            order_by=query.order_by,
        )
