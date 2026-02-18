"""API routers for the dashboard."""

from syn_dashboard.api.artifacts import router as artifacts_router
from syn_dashboard.api.control import router as control_router
from syn_dashboard.api.conversations import router as conversations_router
from syn_dashboard.api.costs import router as costs_router
from syn_dashboard.api.events import router as events_router
from syn_dashboard.api.execution import router as execution_router
from syn_dashboard.api.executions import router as executions_router
from syn_dashboard.api.metrics import router as metrics_router
from syn_dashboard.api.observability import router as observability_router
from syn_dashboard.api.sessions import router as sessions_router
from syn_dashboard.api.triggers import router as triggers_router
from syn_dashboard.api.webhooks import router as webhooks_router
from syn_dashboard.api.websocket import router as websocket_router
from syn_dashboard.api.workflows import router as workflows_router

__all__ = [
    "artifacts_router",
    "control_router",
    "conversations_router",
    "costs_router",
    "events_router",
    "execution_router",
    "executions_router",
    "metrics_router",
    "observability_router",
    "sessions_router",
    "triggers_router",
    "webhooks_router",
    "websocket_router",
    "workflows_router",
]
