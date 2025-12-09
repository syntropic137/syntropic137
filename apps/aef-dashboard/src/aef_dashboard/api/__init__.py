"""API routers for the dashboard."""

from aef_dashboard.api.artifacts import router as artifacts_router
from aef_dashboard.api.events import router as events_router
from aef_dashboard.api.execution import router as execution_router
from aef_dashboard.api.executions import router as executions_router
from aef_dashboard.api.metrics import router as metrics_router
from aef_dashboard.api.observability import router as observability_router
from aef_dashboard.api.sessions import router as sessions_router
from aef_dashboard.api.workflows import router as workflows_router

__all__ = [
    "artifacts_router",
    "events_router",
    "execution_router",
    "executions_router",
    "metrics_router",
    "observability_router",
    "sessions_router",
    "workflows_router",
]
