"""List Repos query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from syn_domain.contexts.organization.slices.list_repos.projection import (
    get_repo_projection,
)

if TYPE_CHECKING:
    from syn_domain.contexts.organization.domain.queries.list_repos import (
        ListReposQuery,
    )
    from syn_domain.contexts.organization.domain.read_models.repo_summary import (
        RepoSummary,
    )


class ListReposHandler:
    async def handle(self, query: ListReposQuery) -> list[RepoSummary]:
        projection = get_repo_projection()
        return await projection.list_all(
            organization_id=query.organization_id,
            system_id=query.system_id,
            provider=query.provider,
            unassigned=query.unassigned,
        )


_handler: ListReposHandler | None = None


def get_list_repos_handler() -> ListReposHandler:
    global _handler
    if _handler is None:
        _handler = ListReposHandler()
    return _handler


def reset_list_repos_handler() -> None:
    global _handler
    _handler = None
