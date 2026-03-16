"""Get metrics query slice."""

from .GetDashboardMetricsHandler import GetDashboardMetricsHandler
from .projection import DashboardMetricsProjection

__all__ = [
    "DashboardMetricsProjection",
    "GetDashboardMetricsHandler",
]
