"""AEF API v1 namespace.

All public operations are available through sub-modules:

    import syn_api.v1.workflows
    import syn_api.v1.executions
    import syn_api.v1.sessions
    import syn_api.v1.artifacts
    import syn_api.v1.metrics
    import syn_api.v1.observability
    import syn_api.v1.conversations
    import syn_api.v1.triggers
    import syn_api.v1.agents
    import syn_api.v1.config
    import syn_api.v1.github
    import syn_api.v1.lifecycle
    import syn_api.v1.realtime
    import syn_api.v1.workspaces
"""

from syn_api.v1 import (
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
