"""AEF API v1 namespace.

All public operations are available through sub-modules:

    import aef_api.v1.workflows
    import aef_api.v1.workspaces
    import aef_api.v1.sessions
    import aef_api.v1.artifacts
    import aef_api.v1.github
    import aef_api.v1.observability
"""

from aef_api.v1 import (
    artifacts,
    github,
    observability,
    sessions,
    workflows,
    workspaces,
)

__all__ = [
    "artifacts",
    "github",
    "observability",
    "sessions",
    "workflows",
    "workspaces",
]
