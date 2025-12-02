"""Get metrics query slice."""

from .handler import GetDashboardMetricsHandler
from .projection import DashboardMetricsProjection

__all__ = [
    "DashboardMetricsProjection",
    "GetDashboardMetricsHandler",
]

