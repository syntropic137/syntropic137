"""Queries for GitHub context."""

from aef_domain.contexts.github.domain.queries.get_installation import (
    GetInstallationQuery,
)
from aef_domain.contexts.github.domain.queries.get_trigger_history import (
    GetTriggerHistoryQuery,
)
from aef_domain.contexts.github.domain.queries.list_accessible_repos import (
    ListAccessibleReposQuery,
)
from aef_domain.contexts.github.domain.queries.list_triggers import (
    ListTriggersQuery,
)

__all__ = [
    "GetInstallationQuery",
    "GetTriggerHistoryQuery",
    "ListAccessibleReposQuery",
    "ListTriggersQuery",
]
