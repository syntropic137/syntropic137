"""Handler for repo correlation queries."""

from syn_domain.contexts.organization.domain.read_models.repo_execution_correlation import (
    RepoExecutionCorrelation,
)

from .projection import RepoCorrelationProjection


class GetReposForExecutionHandler:
    """Query handler: get repos correlated with a specific execution."""

    def __init__(self, projection: RepoCorrelationProjection) -> None:
        self.projection = projection

    async def handle(self, execution_id: str) -> list[RepoExecutionCorrelation]:
        """Handle the query."""
        return await self.projection.get_repos_for_execution(execution_id)


class GetExecutionsForRepoHandler:
    """Query handler: get executions correlated with a specific repo."""

    def __init__(self, projection: RepoCorrelationProjection) -> None:
        self.projection = projection

    async def handle(self, repo_full_name: str) -> list[RepoExecutionCorrelation]:
        """Handle the query."""
        return await self.projection.get_executions_for_repo(repo_full_name)
