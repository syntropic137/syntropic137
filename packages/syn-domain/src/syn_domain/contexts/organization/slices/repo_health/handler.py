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
        # TODO(#176): Look up repo_full_name from repo_id via RepoProjection
        # For now, accept repo_id as repo_full_name
        return await self.projection.get_health(query.repo_id)
