"""Handler for session cost queries."""

from aef_domain.contexts.sessions.domain.queries.get_session_cost import GetSessionCostQuery
from aef_domain.contexts.sessions.domain.read_models.session_cost import SessionCost
from aef_domain.contexts.sessions.slices.session_cost.projection import SessionCostProjection


class SessionCostHandler:
    """Handles GetSessionCostQuery by querying the projection."""

    def __init__(self, projection: SessionCostProjection):
        """Initialize with the session cost projection.

        Args:
            projection: The SessionCostProjection instance to query.
        """
        self._projection = projection

    async def handle(self, query: GetSessionCostQuery) -> SessionCost | None:
        """Execute the query and return session cost.

        Args:
            query: The query parameters.

        Returns:
            SessionCost for the requested session, or None if not found.
        """
        session_cost = await self._projection.get_session_cost(query.session_id)

        if session_cost is None:
            return None

        # Optionally exclude breakdowns
        if not query.include_breakdown:
            session_cost.cost_by_model = {}
            session_cost.cost_by_tool = {}

        return session_cost
