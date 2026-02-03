"""Handler for tool timeline queries."""

from aef_domain.contexts.agent_sessions.domain.queries.get_tool_timeline import (
    GetToolTimelineQuery,
)
from aef_domain.contexts.agent_sessions.domain.read_models.tool_execution import (
    ToolTimeline,
)
from aef_domain.contexts.agent_sessions.slices.tool_timeline.projection import (
    ToolTimelineProjection,
)


class ToolTimelineHandler:
    """Handles GetToolTimelineQuery by querying the projection."""

    def __init__(self, projection: ToolTimelineProjection):
        """Initialize with the tool timeline projection.

        Args:
            projection: The ToolTimelineProjection instance to query.
        """
        self._projection = projection

    async def handle(self, query: GetToolTimelineQuery) -> ToolTimeline:
        """Execute the query and return tool timeline.

        Args:
            query: The query parameters.

        Returns:
            ToolTimeline for the requested session.
        """
        timeline = await self._projection.get_timeline(query.session_id)

        # Apply filters
        if not query.include_blocked:
            filtered_executions = [e for e in timeline.executions if e.status != "blocked"]
            timeline = ToolTimeline.from_executions(
                query.session_id,
                list(filtered_executions),
            )

        # Apply limit
        if len(timeline.executions) > query.limit:
            limited_executions = list(timeline.executions[: query.limit])
            timeline = ToolTimeline.from_executions(
                query.session_id,
                limited_executions,
            )

        return timeline
