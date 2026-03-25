"""Handler for GetSystemCostQuery.

Lazy handler: aggregates per-repo cost snapshots from the repo_cost
store, using in-memory projections for system→repo membership.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol
from syn_domain.contexts.organization._shared.projection_names import REPO_COST
from syn_domain.contexts.organization.domain.queries.get_system_cost import (
    GetSystemCostQuery,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_domain.contexts.organization.domain.read_models.system_cost import SystemCost
from syn_domain.contexts.organization.slices.list_repos.projection import (
    RepoProjection,
)
from syn_domain.contexts.organization.slices.list_systems.projection import (
    SystemProjection,
)


@dataclass
class _AggregatedCost:
    """Accumulator for aggregating repo costs into system cost."""

    total_cost: Decimal = Decimal("0")
    total_tokens: int = 0
    total_input: int = 0
    total_output: int = 0
    execution_count: int = 0
    cost_by_repo: dict[str, Decimal] = field(default_factory=dict)
    cost_by_workflow: dict[str, Decimal] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)

    def add_repo(self, full_name: str, rc: RepoCost) -> None:
        """Accumulate one repo's cost into the aggregate."""
        self.total_cost += rc.total_cost_usd
        self.total_tokens += rc.total_tokens
        self.total_input += rc.total_input_tokens
        self.total_output += rc.total_output_tokens
        self.execution_count += rc.execution_count

        if rc.total_cost_usd > 0:
            self.cost_by_repo[full_name] = rc.total_cost_usd

        for wf, cost in rc.cost_by_workflow.items():
            self.cost_by_workflow[wf] = self.cost_by_workflow.get(wf, Decimal("0")) + cost
        for model, cost in rc.cost_by_model.items():
            self.cost_by_model[model] = self.cost_by_model.get(model, Decimal("0")) + cost


class GetSystemCostHandler:
    """Query handler: get a system's cost breakdown."""

    def __init__(
        self,
        store: ProjectionStoreProtocol,
        system_projection: SystemProjection,
        repo_projection: RepoProjection,
    ) -> None:
        self._store = store
        self._system_projection = system_projection
        self._repo_projection = repo_projection

    async def handle(self, query: GetSystemCostQuery) -> SystemCost:
        """Handle GetSystemCostQuery."""
        system = await self._system_projection.get(query.system_id)
        system_name = system.name if system else ""
        organization_id = system.organization_id if system else ""

        repos = await self._repo_projection.list_all(system_id=query.system_id)
        agg = _AggregatedCost()

        for repo in repos:
            cost_data = await self._store.get(REPO_COST, repo.full_name)
            if not cost_data:
                continue
            agg.add_repo(repo.full_name, RepoCost.from_dict(cost_data))

        return SystemCost(
            system_id=query.system_id,
            system_name=system_name,
            organization_id=organization_id,
            total_cost_usd=agg.total_cost,
            total_tokens=agg.total_tokens,
            total_input_tokens=agg.total_input,
            total_output_tokens=agg.total_output,
            cost_by_repo=agg.cost_by_repo,
            cost_by_workflow=agg.cost_by_workflow,
            cost_by_model=agg.cost_by_model,
            execution_count=agg.execution_count,
        )
