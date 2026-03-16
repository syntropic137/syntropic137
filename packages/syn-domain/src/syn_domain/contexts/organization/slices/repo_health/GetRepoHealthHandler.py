"""Handler for GetRepoHealthQuery."""

from syn_domain.contexts.organization.domain.queries.get_repo_health import (
    GetRepoHealthQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth

from .projection import RepoHealthProjection


class GetRepoHealthHandler:
    """Query handler: get a repo's health snapshot."""

    def __init__(self, projection: RepoHealthProjection) -> None:
        self.projection = projection

    async def handle(self, query: GetRepoHealthQuery) -> RepoHealth:
        """Handle GetRepoHealthQuery.

        Uses the repo_id to find the repo's full_name via the repo
        projection, then queries the health projection.
        """
        key = query.repo_full_name or query.repo_id
        return await self.projection.get_health(key)
