"""TimescaleDB direct query for repo cost calculation.

Queries the agent_events table to aggregate token usage and costs
per repository. Joins through the repo-execution correlation
(stored in the projection store) to map execution-level costs
to repositories.

Pattern follows TimescaleSessionCostQuery from the session_cost slice.
"""

from __future__ import annotations

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


class TimescaleRepoCostQuery:
    """Calculates per-repo cost from TimescaleDB via repo-execution correlation.

    Requires the projection store for looking up which executions
    belong to which repos (repo_correlation projection).
    """

    def __init__(self, pool: Any, projection_store: Any) -> None:
        self._pool = pool
        self._store = projection_store

    async def _get_execution_ids_for_repo(self, repo_full_name: str) -> list[str]:
        """Look up execution IDs correlated with a repo."""
        from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

        correlations = await self._store.query(
            REPO_CORRELATION, filters={"repo_full_name": repo_full_name}
        )
        return [c["execution_id"] for c in correlations if c.get("execution_id")]

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
            # Try session_summary aggregation first
            rows = await conn.fetch(_EXECUTION_COSTS_QUERY, SESSION_SUMMARY, execution_ids)

            total_cost = Decimal("0")
            total_input = 0
            total_output = 0
            execution_count = 0

            if rows:
                for row in rows:
                    if row["total_input"] is not None:
                        total_input += row["total_input"] or 0
                        total_output += row["total_output"] or 0
                        if row["total_cost"] is not None:
                            total_cost += Decimal(str(row["total_cost"]))
                        execution_count += 1
            else:
                # Fallback to token_usage aggregation
                fallback_rows = await conn.fetch(
                    _EXECUTION_COSTS_FALLBACK_QUERY, TOKEN_USAGE, execution_ids
                )
                for row in fallback_rows:
                    if row["total_input"] is not None:
                        total_input += row["total_input"] or 0
                        total_output += row["total_output"] or 0
                        execution_count += 1

            return RepoCost(
                repo_full_name=repo_full_name,
                total_cost_usd=total_cost,
                total_tokens=total_input + total_output,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                execution_count=execution_count,
            )

    async def calculate_all(self) -> list[RepoCost]:
        """Calculate costs for all repos that have correlated executions.

        Returns:
            List of RepoCost for all repos with execution data.
        """
        from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION

        all_correlations = await self._store.get_all(REPO_CORRELATION)
        if not all_correlations:
            return []

        # Group execution IDs by repo
        repo_executions: dict[str, list[str]] = {}
        for c in all_correlations:
            repo = c.get("repo_full_name", "")
            exec_id = c.get("execution_id", "")
            if repo and exec_id:
                repo_executions.setdefault(repo, []).append(exec_id)

        if not repo_executions:
            return []

        # Query all execution costs in one batch
        all_execution_ids = [eid for eids in repo_executions.values() for eid in eids]

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_EXECUTION_COSTS_QUERY, SESSION_SUMMARY, all_execution_ids)

            # Build per-execution cost map
            exec_costs: dict[str, dict[str, Any]] = {}
            for row in rows:
                if row["total_input"] is not None:
                    exec_costs[row["execution_id"]] = {
                        "total_input": row["total_input"] or 0,
                        "total_output": row["total_output"] or 0,
                        "total_cost": Decimal(str(row["total_cost"]))
                        if row["total_cost"]
                        else Decimal("0"),
                    }

            # If no session_summary data, try token_usage
            missing_ids = [eid for eid in all_execution_ids if eid not in exec_costs]
            if missing_ids:
                fallback_rows = await conn.fetch(
                    _EXECUTION_COSTS_FALLBACK_QUERY, TOKEN_USAGE, missing_ids
                )
                for row in fallback_rows:
                    if row["total_input"] is not None:
                        exec_costs[row["execution_id"]] = {
                            "total_input": row["total_input"] or 0,
                            "total_output": row["total_output"] or 0,
                            "total_cost": Decimal("0"),
                        }

        # Aggregate per repo
        results: list[RepoCost] = []
        for repo, eids in repo_executions.items():
            total_cost = Decimal("0")
            total_input = 0
            total_output = 0
            execution_count = 0
            for eid in eids:
                if eid in exec_costs:
                    ec = exec_costs[eid]
                    total_input += ec["total_input"]
                    total_output += ec["total_output"]
                    total_cost += ec["total_cost"]
                    execution_count += 1

            if execution_count > 0:
                results.append(
                    RepoCost(
                        repo_full_name=repo,
                        total_cost_usd=total_cost,
                        total_tokens=total_input + total_output,
                        total_input_tokens=total_input,
                        total_output_tokens=total_output,
                        execution_count=execution_count,
                    )
                )

        return results
