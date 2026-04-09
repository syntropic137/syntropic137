"""Repo health projection.

Eagerly maintains per-repo health snapshots by observing workflow
completion and failure events, correlated to repos via the shared
ProjectionStore.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syn_adapters.projection_stores.protocol import ProjectionStoreProtocol

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.organization._shared.projection_names import (
    REPO_CORRELATION,
    REPO_HEALTH,
)
from syn_domain.contexts.organization.domain.read_models.repo_health import RepoHealth

logger = logging.getLogger(__name__)

_SNAPSHOT_INTERVAL = 100
_TREND_WINDOW = 10  # Last N executions for trend calculation


def _update_execution_counts(health: dict[str, Any], success: bool) -> None:
    """Update execution counts and success rate."""
    health["total_executions"] = health.get("total_executions", 0) + 1
    key = "successful_executions" if success else "failed_executions"
    health[key] = health.get(key, 0) + 1
    total = health["total_executions"]
    if total > 0:
        health["success_rate"] = health.get("successful_executions", 0) / total


def _update_cost_tokens(health: dict[str, Any], cost_usd: str, tokens: int) -> None:
    """Accumulate cost and token metrics."""
    existing_cost = Decimal(str(health.get("recent_cost_usd", "0")))
    health["recent_cost_usd"] = str(existing_cost + Decimal(cost_usd))
    health["window_tokens"] = health.get("window_tokens", 0) + tokens


def _update_trend(health: dict[str, Any], success: bool) -> None:
    """Update trend based on recent outcomes vs overall success rate."""
    recent: list[bool] = health.get("_recent_outcomes", [])
    recent.append(success)
    if len(recent) > _TREND_WINDOW:
        recent = recent[-_TREND_WINDOW:]
    health["_recent_outcomes"] = recent

    if len(recent) < 3:
        return

    recent_rate = sum(1 for x in recent if x) / len(recent)
    overall_rate = health.get("success_rate", 0)
    if recent_rate > overall_rate + 0.05:
        health["trend"] = "improving"
    elif recent_rate < overall_rate - 0.05:
        health["trend"] = "degrading"
    else:
        health["trend"] = "stable"


class RepoHealthProjection(AutoDispatchProjection):
    """Per-repo health projection.

    Handles WorkflowCompleted and WorkflowFailed events. Looks up the
    repo-execution correlation from the shared ProjectionStore to determine
    which repos an execution belongs to.
    """

    PROJECTION_NAME = REPO_HEALTH
    VERSION = 1

    def __init__(self, store: ProjectionStoreProtocol) -> None:
        self._store = store
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
        """Get existing health data or create empty."""
        existing: dict[str, Any] | None = await self._store.get(
            self.PROJECTION_NAME, repo_full_name
        )
        if existing:
            return existing
        return RepoHealth(repo_full_name=repo_full_name).to_dict()

    async def _save(self, repo_full_name: str, data: dict[str, Any]) -> None:
        await self._store.save(self.PROJECTION_NAME, repo_full_name, data)
        self._events_since_snapshot += 1
        if self._events_since_snapshot >= _SNAPSHOT_INTERVAL:
            self._events_since_snapshot = 0

    async def _update_repo(
        self,
        repo_full_name: str,
        *,
        success: bool,
        cost_usd: str,
        tokens: int,
        timestamp: str,
    ) -> None:
        """Update a repo's health metrics for one execution outcome."""
        health = await self._get_or_create(repo_full_name)

        _update_execution_counts(health, success)
        _update_cost_tokens(health, cost_usd, tokens)

        if timestamp:
            health["last_execution_at"] = timestamp

        _update_trend(health, success)
        await self._save(repo_full_name, health)

    async def on_workflow_completed(self, event_data: dict[str, Any]) -> None:
        """Handle WorkflowCompleted — update health for correlated repos."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        repos = await self._get_correlated_repos(execution_id)
        cost = str(event_data.get("total_cost_usd", "0"))
        tokens = event_data.get("total_tokens", 0)
        timestamp = str(event_data.get("completed_at", ""))

        for repo in repos:
            await self._update_repo(
                repo, success=True, cost_usd=cost, tokens=tokens, timestamp=timestamp
            )

    async def on_workflow_failed(self, event_data: dict[str, Any]) -> None:
        """Handle WorkflowFailed — update health for correlated repos."""
        execution_id = event_data.get("execution_id", "")
        if not execution_id:
            return

        repos = await self._get_correlated_repos(execution_id)
        cost = str(event_data.get("total_cost_usd", "0"))
        tokens = event_data.get("total_tokens", 0)
        timestamp = str(event_data.get("failed_at", ""))

        for repo in repos:
            await self._update_repo(
                repo, success=False, cost_usd=cost, tokens=tokens, timestamp=timestamp
            )

    # --- Query methods ---

    async def get_health(self, repo_full_name: str) -> RepoHealth:
        """Get health snapshot for a repo."""
        data = await self._get_or_create(repo_full_name)
        # Strip internal tracking fields before returning
        clean = {k: v for k, v in data.items() if not k.startswith("_")}
        return RepoHealth.from_dict(clean)

    async def get_all_health(self) -> list[RepoHealth]:
        """Get health snapshots for all repos."""
        all_data = await self._store.get_all(self.PROJECTION_NAME)
        return [
            RepoHealth.from_dict({k: v for k, v in d.items() if not k.startswith("_")})
            for d in all_data
        ]
