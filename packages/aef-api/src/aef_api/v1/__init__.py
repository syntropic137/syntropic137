"""AEF API v1 namespace.

All public operations are available through sub-modules:

    import aef_api.v1.workflows
    import aef_api.v1.workspaces
    import aef_api.v1.sessions
    import aef_api.v1.triggers
    import aef_api.v1.agents
    import aef_api.v1.config
    import aef_api.v1.artifacts
    import aef_api.v1.github
    import aef_api.v1.observability
"""

from aef_api.v1 import (
    agents,
    artifacts,
    config,
    github,
    observability,
    sessions,
    triggers,
    workflows,
    workspaces,
)

__all__ = [
    "agents",
    "artifacts",
    "config",
    "github",
    "observability",
    "sessions",
    "triggers",
    "workflows",
    "workspaces",
]
