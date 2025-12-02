"""Query DTO for dashboard metrics."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GetDashboardMetricsQuery:
    """Query to get dashboard metrics.

    This is a simple query with no parameters as it retrieves
    aggregate metrics for the entire system.
    """

    include_cost_breakdown: bool = False
    """Whether to include detailed cost breakdown by agent type."""
