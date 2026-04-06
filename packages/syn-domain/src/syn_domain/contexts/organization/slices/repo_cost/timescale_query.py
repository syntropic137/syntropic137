"""TimescaleDB direct query for repo cost calculation.

Queries the agent_events table to aggregate token usage and costs
per repository. Joins through the repo-execution correlation
(stored in the projection store) to map execution-level costs
to repositories.

Pattern follows TimescaleSessionCostQuery from the session_cost slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost
from syn_shared.events import SESSION_SUMMARY, TOKEN_USAGE

# Aggregate cost per execution from session_summary (authoritative)
_EXECUTION_COSTS_QUERY = """
SELECT
    execution_id,
    SUM((data->>'total_input_tokens')::int) as total_input,
    SUM((data->>'total_output_tokens')::int) as total_output,
    SUM((data->>'total_cost_usd')::numeric) as total_cost
FROM agent_events
WHERE event_type = $1
  AND execution_id = ANY($2)
GROUP BY execution_id
"""

# Fallback: aggregate from token_usage when no session_summary exists
_EXECUTION_COSTS_FALLBACK_QUERY = """
SELECT
    execution_id,
    SUM((data->>'input_tokens')::int) as total_input,
    SUM((data->>'output_tokens')::int) as total_output
FROM agent_events
WHERE event_type = $1
  AND execution_id = ANY($2)
GROUP BY execution_id
"""


@dataclass
class _ExecutionCostEntry:
    """Cost data for a single execution."""

    total_input: int
    total_output: int
    total_cost: Decimal


class TimescaleRepoCostQuery:
    """Calculates per-repo cost from TimescaleDB via repo-execution correlation.

    Requires the projection store for looking up which executions
    belong to which repos (repo_correlation projection).
    """

    def __init__(self, pool: Any, projection_store: Any) -> None:  # noqa: ANN401
        self._pool = pool
        self._store = projection_store

    async def _get_execution_ids_for_repo(self, repo_full_name: str) -> list[str]:
        """Look up execution IDs correlated with a repo."""
        from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

        correlations = await self._store.query(
            REPO_CORRELATION, filters={"repo_full_name": repo_full_name}
        )
        return [c["execution_id"] for c in correlations if c.get("execution_id")]

    async def _query_summary_costs(
        self, conn: Any, execution_ids: list[str]  # noqa: ANN401
    ) -> dict[str, _ExecutionCostEntry]:
        """Query session_summary costs grouped by execution_id."""
        rows = await conn.fetch(_EXECUTION_COSTS_QUERY, SESSION_SUMMARY, execution_ids)
        result: dict[str, _ExecutionCostEntry] = {}
        for row in rows:
            if row["total_input"] is not None:
                result[row["execution_id"]] = _ExecutionCostEntry(
                    total_input=row["total_input"] or 0,
                    total_output=row["total_output"] or 0,
                    total_cost=Decimal(str(row["total_cost"]))
                    if row["total_cost"]
                    else Decimal("0"),
                )
        return result

    async def _query_fallback_costs(
        self, conn: Any, execution_ids: list[str]  # noqa: ANN401
    ) -> dict[str, _ExecutionCostEntry]:
        """Query token_usage costs as fallback for missing summary data."""
        rows = await conn.fetch(_EXECUTION_COSTS_FALLBACK_QUERY, TOKEN_USAGE, execution_ids)
        result: dict[str, _ExecutionCostEntry] = {}
        for row in rows:
            if row["total_input"] is not None:
                result[row["execution_id"]] = _ExecutionCostEntry(
                    total_input=row["total_input"] or 0,
                    total_output=row["total_output"] or 0,
                    total_cost=Decimal("0"),
                )
        return result

    def _aggregate_repo_cost(
        self,
        repo_full_name: str,
        execution_ids: list[str],
        exec_costs: dict[str, _ExecutionCostEntry],
    ) -> RepoCost | None:
        """Aggregate execution costs into a single RepoCost for a repo."""
        total_cost = Decimal("0")
        total_input = 0
        total_output = 0
        execution_count = 0
        for eid in execution_ids:
            if eid in exec_costs:
                entry = exec_costs[eid]
                total_input += entry.total_input
                total_output += entry.total_output
                total_cost += entry.total_cost
                execution_count += 1

        if execution_count == 0:
            return None

        return RepoCost(
            repo_full_name=repo_full_name,
            total_cost_usd=total_cost,
            total_tokens=total_input + total_output,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            execution_count=execution_count,
        )

    async def calculate_for_repo(self, repo_full_name: str) -> RepoCost:
        """Calculate cost for a single repo from TimescaleDB.

        Returns:
            RepoCost with aggregated metrics. Returns zero-cost RepoCost
            if no executions found (never returns None, matching projection
            store behavior).
        """
        execution_ids = await self._get_execution_ids_for_repo(repo_full_name)
        if not execution_ids:
            return RepoCost(repo_full_name=repo_full_name)

        async with self._pool.acquire() as conn:
            exec_costs = await self._query_summary_costs(conn, execution_ids)
            if not exec_costs:
                exec_costs = await self._query_fallback_costs(conn, execution_ids)

        result = self._aggregate_repo_cost(repo_full_name, execution_ids, exec_costs)
        return result or RepoCost(repo_full_name=repo_full_name)

    async def _get_all_repo_executions(self) -> dict[str, list[str]]:
        """Load all repo-to-execution mappings from the correlation store."""
        from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

        all_correlations = await self._store.get_all(REPO_CORRELATION)
        if not all_correlations:
            return {}

        repo_executions: dict[str, list[str]] = {}
        for c in all_correlations:
            repo = c.get("repo_full_name", "")
            exec_id = c.get("execution_id", "")
            if repo and exec_id:
                repo_executions.setdefault(repo, []).append(exec_id)
        return repo_executions

    async def _query_all_exec_costs(
        self, conn: Any, all_execution_ids: list[str]  # noqa: ANN401
    ) -> dict[str, _ExecutionCostEntry]:
        """Query costs for all executions, with fallback for missing summaries."""
        exec_costs = await self._query_summary_costs(conn, all_execution_ids)

        missing_ids = [eid for eid in all_execution_ids if eid not in exec_costs]
        if missing_ids:
            fallback = await self._query_fallback_costs(conn, missing_ids)
            exec_costs.update(fallback)

        return exec_costs

    async def calculate_all(self) -> list[RepoCost]:
        """Calculate costs for all repos that have correlated executions.

        Returns:
            List of RepoCost for all repos with execution data.
        """
        repo_executions = await self._get_all_repo_executions()
        if not repo_executions:
            return []

        all_execution_ids = [eid for eids in repo_executions.values() for eid in eids]

        async with self._pool.acquire() as conn:
            exec_costs = await self._query_all_exec_costs(conn, all_execution_ids)

        results: list[RepoCost] = []
        for repo, eids in repo_executions.items():
            cost = self._aggregate_repo_cost(repo, eids, exec_costs)
            if cost is not None:
                results.append(cost)

        return results
