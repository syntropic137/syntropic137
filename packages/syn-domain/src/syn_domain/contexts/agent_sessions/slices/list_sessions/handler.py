"""Handler for list_sessions query."""

from syn_domain.contexts.agent_sessions.domain.queries.list_sessions import (
    ListSessionsQuery,
)
from syn_domain.contexts.agent_sessions.domain.read_models.session_summary import (
    SessionSummary,
)

from .projection import SessionListProjection


class ListSessionsHandler:
    """Query Handler for list_sessions.

    This handler retrieves data from the SessionListProjection.
    """

    def __init__(self, projection: SessionListProjection):
        self.projection = projection

    async def handle(self, query: ListSessionsQuery) -> list[SessionSummary]:
        """Handle ListSessionsQuery."""
        return await self.projection.query(
            workflow_id=query.workflow_id,
            status_filter=query.status_filter,
            limit=query.limit,
            offset=query.offset,
            order_by=query.order_by,
        )
