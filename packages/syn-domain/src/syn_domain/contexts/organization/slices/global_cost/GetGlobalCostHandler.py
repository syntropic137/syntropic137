"""Handler for GetGlobalCostQuery.

Lazy handler: aggregates per-repo cost snapshots across all repos
from the repo_cost store.
"""

from decimal import Decimal

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import REPO_COST
from syn_domain.contexts.organization.domain.queries.get_global_cost import (
    GetGlobalCostQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.system_cost import SystemCost
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)


class GetGlobalCostHandler:
    """Query handler: get global cost breakdown."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._repo_projection = repo_projection

    async def handle(self, query: GetGlobalCostQuery) -> SystemCost:
        """Handle GetGlobalCostQuery."""
        repos = await self._repo_projection.list_all()

        total_cost = Decimal("0")
        total_tokens = 0
        total_input = 0
        total_output = 0
        execution_count = 0
        cost_by_repo: dict[str, Decimal] = {}
        cost_by_workflow: dict[str, Decimal] = {}
        cost_by_model: dict[str, Decimal] = {}

        for repo in repos:
            cost_data = await self._store.get(REPO_COST, repo.full_name)
            if not cost_data:
                continue
            rc = RepoCost.from_dict(cost_data)

            total_cost += rc.total_cost_usd
            total_tokens += rc.total_tokens
            total_input += rc.total_input_tokens
            total_output += rc.total_output_tokens
            execution_count += rc.execution_count

            if rc.total_cost_usd > 0:
                cost_by_repo[repo.full_name] = rc.total_cost_usd

            for wf, cost in rc.cost_by_workflow.items():
                cost_by_workflow[wf] = cost_by_workflow.get(wf, Decimal("0")) + cost
            for model, cost in rc.cost_by_model.items():
                cost_by_model[model] = cost_by_model.get(model, Decimal("0")) + cost

        return SystemCost(
            system_id="",
            system_name="global",
            total_cost_usd=total_cost,
            total_tokens=total_tokens,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            cost_by_repo=cost_by_repo,
            cost_by_workflow=cost_by_workflow,
            cost_by_model=cost_by_model,
            execution_count=execution_count,
        )
