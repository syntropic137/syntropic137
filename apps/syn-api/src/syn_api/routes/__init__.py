"""API routers."""

from syn_api.routes.agents import router as agents_router
from syn_api.routes.artifacts import router as artifacts_router
from syn_api.routes.conversations import router as conversations_router
from syn_api.routes.costs import router as costs_router
from syn_api.routes.events import router as events_router
from syn_api.routes.executions import router as executions_router
from syn_api.routes.insights import router as insights_router
from syn_api.routes.metrics import router as metrics_router
from syn_api.routes.observability import router as observability_router
from syn_api.routes.organizations import router as organizations_router
from syn_api.routes.repos import router as repos_router
from syn_api.routes.sessions import router as sessions_router
from syn_api.routes.sse import router as sse_router
from syn_api.routes.systems import router as systems_router
from syn_api.routes.triggers import router as triggers_router
from syn_api.routes.webhooks import router as webhooks_router
from syn_api.routes.workflows import router as workflows_router

__all__ = [
    "agents_router",
    "artifacts_router",
    "conversations_router",
    "costs_router",
    "events_router",
    "executions_router",
    "insights_router",
    "metrics_router",
    "observability_router",
    "organizations_router",
    "repos_router",
    "sessions_router",
    "sse_router",
    "systems_router",
    "triggers_router",
    "webhooks_router",
    "workflows_router",
]
