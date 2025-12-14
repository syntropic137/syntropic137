"""Handler for execution cost queries."""

from aef_domain.contexts.costs.domain.queries.get_execution_cost import GetExecutionCostQuery
from aef_domain.contexts.costs.domain.read_models.execution_cost import ExecutionCost
from aef_domain.contexts.costs.slices.execution_cost.projection import ExecutionCostProjection


class ExecutionCostHandler:
    """Handles GetExecutionCostQuery by querying the projection."""

    def __init__(self, projection: ExecutionCostProjection):
        """Initialize with the execution cost projection.

        Args:
            projection: The ExecutionCostProjection instance to query.
        """
        self._projection = projection

    async def handle(self, query: GetExecutionCostQuery) -> ExecutionCost | None:
        """Execute the query and return execution cost.

        Args:
            query: The query parameters.

        Returns:
            ExecutionCost for the requested execution, or None if not found.
        """
        execution_cost = await self._projection.get_execution_cost(query.execution_id)

        if execution_cost is None:
            return None

        # Optionally exclude breakdowns
        if not query.include_breakdown:
            execution_cost.cost_by_phase = {}
            execution_cost.cost_by_model = {}
            execution_cost.cost_by_tool = {}

        # Optionally exclude session IDs
        if not query.include_session_ids:
            execution_cost.session_ids = []

        return execution_cost
