"""Repo cost projection.

Eagerly maintains per-repo cost breakdowns by observing workflow
completion and failure events, correlated to repos via the shared
ProjectionStore.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.organization._shared.projection_names import (
    REPO_CORRELATION,
    REPO_COST,
)
from syn_domain.contexts.organization.domain.read_models.repo_cost import RepoCost

logger = logging.getLogger(__name__)

_SNAPSHOT_INTERVAL = 100


class RepoCostProjection(AutoDispatchProjection):
    """Per-repo cost breakdown projection.

    Handles WorkflowCompleted and WorkflowFailed events. Looks up the
    repo-execution correlation from the shared ProjectionStore.

    Data Sources:
    - TimescaleDB: agent_events table (session_summary, token_usage) — preferred
    - Projection Store: fallback for environments without TimescaleDB
    """

    PROJECTION_NAME = REPO_COST
    VERSION = 1

    def __init__(self, store: Any, pool: Any | None = None) -> None:  # noqa: ANN401
        self._store = store
        self._pool = pool
        self._events_since_snapshot = 0

    def get_name(self) -> str:
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        return self.VERSION

    async def clear_all_data(self) -> None:
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def _get_correlated_repos(self, execution_id: str) -> list[str]:
        """Look up repos for an execution from the correlation store."""
        correlations = await self._store.query(
            REPO_CORRELATION, filters={"execution_id": execution_id}
        )
        return [c["repo_full_name"] for c in correlations]

    async def _get_or_create(self, repo_full_name: str) -> dict[str, Any]:
        existing: dict[str, Any] | None = await self._store.get(
            self.PROJECTION_NAME, repo_full_name
        )
        if existing:
            return existing
        return RepoCost(repo_full_name=repo_full_name).to_dict()

    async def _save(self, repo_full_name: str, data: dict[str, Any]) -> None:
        await self._store.save(self.PROJECTION_NAME, repo_full_name, data)
        self._events_since_snapshot += 1
        if self._events_since_snapshot >= _SNAPSHOT_INTERVAL:
            self._events_since_snapshot = 0

    async def _record_cost(
        self,
        repo_full_name: str,
        *,
        workflow_id: str,
        cost_usd: str,
        total_tokens: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record cost from one execution for a repo."""
        data = await self._get_or_create(repo_full_name)

        existing_cost = Decimal(str(data.get("total_cost_usd", "0")))
        data["total_cost_usd"] = str(existing_cost + Decimal(cost_usd))
        data["total_tokens"] = data.get("total_tokens", 0) + total_tokens
        data["total_input_tokens"] = data.get("total_input_tokens", 0) + input_tokens
        data["total_output_tokens"] = data.get("total_output_tokens", 0) + output_tokens
        data["execution_count"] = data.get("execution_count", 0) + 1

        # Cost by workflow
        by_wf: dict[str, str] = data.get("cost_by_workflow", {})
        wf_cost = Decimal(by_wf.get(workflow_id, "0"))
        by_wf[workflow_id] = str(wf_cost + Decimal(cost_usd))
        data["cost_by_workflow"] = by_wf

        # TODO(#199): cost_by_model requires per-model token/cost breakdowns from
        # workflow events, which are not yet available. This field will remain empty
        # until events carry model-level granularity.

        await self._save(repo_full_name, data)

    async def _handle_execution_event(self, event_data: dict[str, Any]) -> None:
        """Common handler for both completed and failed events."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        repos = await self._get_correlated_repos(execution_id)
        workflow_id = event_data.get("workflow_id", "")
        cost = str(event_data.get("total_cost_usd", "0"))
        total_tokens = event_data.get("total_tokens", 0)
        input_tokens = event_data.get("total_input_tokens", 0)
        output_tokens = event_data.get("total_output_tokens", 0)

        for repo in repos:
            await self._record_cost(
                repo,
                workflow_id=workflow_id,
                cost_usd=cost,
                total_tokens=total_tokens,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )

    async def on_workflow_completed(self, event_data: dict[str, Any]) -> None:
        """Handle WorkflowCompleted — record cost for correlated repos."""
        await self._handle_execution_event(event_data)

    async def on_workflow_failed(self, event_data: dict[str, Any]) -> None:
        """Handle WorkflowFailed — record cost for correlated repos."""
        await self._handle_execution_event(event_data)

    # --- Query methods ---

    async def get_cost(self, repo_full_name: str) -> RepoCost:
        """Get cost breakdown for a repo.

        Queries TimescaleDB directly when a pool is available (preferred).
        Falls back to projection store for environments without TimescaleDB.
        """
        if self._pool is not None:
            return await self._query_timescale_for_repo(repo_full_name)

        # Fallback to projection store (legacy path)
        data = await self._get_or_create(repo_full_name)
        return RepoCost.from_dict(data)

    async def _query_timescale_for_repo(self, repo_full_name: str) -> RepoCost:
        """Calculate repo cost directly from TimescaleDB observations.

        Delegates to TimescaleRepoCostQuery for the actual computation.

        Args:
            repo_full_name: Full repository name (e.g. "owner/repo")

        Returns:
            RepoCost with aggregated metrics (zero-cost if no data found)
        """
        if self._pool is None:
            data = await self._get_or_create(repo_full_name)
            return RepoCost.from_dict(data)
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        query = TimescaleRepoCostQuery(self._pool, self._store)
        return await query.calculate_for_repo(repo_full_name)

    async def get_all_costs(self) -> list[RepoCost]:
        """Get cost breakdowns for all repos.

        Queries TimescaleDB directly when a pool is available (preferred).
        Falls back to projection store for environments without TimescaleDB.
        """
        if self._pool is not None:
            return await self._query_timescale_all()

        # Fallback to projection store (legacy path)
        all_data = await self._store.get_all(self.PROJECTION_NAME)
        return [RepoCost.from_dict(d) for d in all_data]

    async def _query_timescale_all(self) -> list[RepoCost]:
        """Calculate all repo costs from TimescaleDB."""
        if self._pool is None:
            all_data = await self._store.get_all(self.PROJECTION_NAME)
            return [RepoCost.from_dict(d) for d in all_data]
        from syn_domain.contexts.organization.slices.repo_cost.timescale_query import (
            TimescaleRepoCostQuery,
        )

        query = TimescaleRepoCostQuery(self._pool, self._store)
        return await query.calculate_all()
