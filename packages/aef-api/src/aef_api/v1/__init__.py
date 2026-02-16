"""AEF API v1 namespace.

All public operations are available through sub-modules:

    import aef_api.v1.workflows
    import aef_api.v1.executions
    import aef_api.v1.sessions
    import aef_api.v1.artifacts
    import aef_api.v1.metrics
    import aef_api.v1.observability
    import aef_api.v1.conversations
    import aef_api.v1.triggers
    import aef_api.v1.agents
    import aef_api.v1.config
    import aef_api.v1.github
    import aef_api.v1.lifecycle
    import aef_api.v1.realtime
    import aef_api.v1.workspaces
"""

from aef_api.v1 import (
    agents,
    artifacts,
    config,
    conversations,
    executions,
    github,
    lifecycle,
    metrics,
    observability,
    realtime,
    sessions,
    triggers,
    workflows,
    workspaces,
)

__all__ = [
    "agents",
    "artifacts",
    "config",
    "conversations",
    "executions",
    "github",
    "lifecycle",
    "metrics",
    "observability",
    "realtime",
    "sessions",
    "triggers",
    "workflows",
    "workspaces",
]
