"""Handler for GetRepoCostQuery."""

from syn_domain.contexts.organization.domain.queries.get_repo_cost import (
    GetRepoCostQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost

from .projection import RepoCostProjection


class GetRepoCostHandler:
    """Query handler: get a repo's cost breakdown."""

    def __init__(self, projection: RepoCostProjection) -> None:
        self.projection = projection

    async def handle(self, query: GetRepoCostQuery) -> RepoCost:
        """Handle GetRepoCostQuery."""
        key = query.repo_full_name or query.repo_id
        return await self.projection.get_cost(key)
