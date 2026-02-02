"""Handler for get_dashboard_metrics query."""

from aef_domain.contexts.orchestration.domain.queries.get_dashboard_metrics import (
    GetDashboardMetricsQuery,
)
from aef_domain.contexts.orchestration.domain.read_models.dashboard_metrics import (
    DashboardMetrics,
)

from .projection import DashboardMetricsProjection


class GetDashboardMetricsHandler:
    """Query Handler for get_dashboard_metrics.

    This handler retrieves aggregate metrics from the DashboardMetricsProjection.
    """

    def __init__(self, projection: DashboardMetricsProjection):
        self.projection = projection

    async def handle(self, _query: GetDashboardMetricsQuery) -> DashboardMetrics:
        """Handle GetDashboardMetricsQuery."""
        # Currently we ignore include_cost_breakdown flag
        # Future: could return additional breakdown data
        return await self.projection.get_metrics()
