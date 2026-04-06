"""List Repos slice — query accessible GitHub App repositories."""

from syn_domain.contexts.github.slices.list_repos.handler import (
    ListAccessibleReposHandler,
)

__all__ = ["ListAccessibleReposHandler"]
