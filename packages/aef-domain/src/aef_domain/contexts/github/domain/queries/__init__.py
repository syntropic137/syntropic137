"""Queries for GitHub context."""

from aef_domain.contexts.github.domain.queries.get_installation import (
    GetInstallationQuery,
)
from aef_domain.contexts.github.domain.queries.list_accessible_repos import (
    ListAccessibleReposQuery,
)

__all__ = [
    "GetInstallationQuery",
    "ListAccessibleReposQuery",
]
