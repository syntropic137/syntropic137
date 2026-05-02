"""Repo-execution correlation projection.

Uses AutoDispatchProjection + ProjectionStore to map repositories
to workflow executions. Correlation is derived from TriggerFired
and WorkflowExecutionStarted events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from event_sourcing import ProjectionStore

from event_sourcing import AutoDispatchProjection

from syn_domain.contexts.organization._shared.projection_names import REPO_CORRELATION
from syn_domain.contexts.organization.domain.read_models.repo_execution_correlation import (
    RepoExecutionCorrelation,
)

logger = logging.getLogger(__name__)


class RepoCorrelationProjection(AutoDispatchProjection):
    """Maps repos ↔ executions from trigger and execution events.

    Uses AutoDispatchProjection: define on_<snake_case_event> methods to
    subscribe and handle events — no separate subscription set needed.
    """

    PROJECTION_NAME = REPO_CORRELATION
    VERSION = 1

    def __init__(self, store: ProjectionStore) -> None:
        """Initialize with a projection store.

        Args:
            store: A ProjectionStore implementation.
        """
        self._store = store

    def get_name(self) -> str:
        """Unique projection name for checkpoint tracking."""
        return self.PROJECTION_NAME

    def get_version(self) -> int:
        """Schema version — increment to trigger rebuild."""
        return self.VERSION

    async def clear_all_data(self) -> None:
        """Clear projection data for rebuild."""
        if hasattr(self._store, "delete_all"):
            await self._store.delete_all(self.PROJECTION_NAME)

    async def _save_correlation(self, correlation: RepoExecutionCorrelation) -> None:
        """Save a correlation record, keyed by execution_id:repo_full_name."""
        key = f"{correlation.execution_id}:{correlation.repo_full_name}"
        await self._store.save(self.PROJECTION_NAME, key, correlation.to_dict())

    # --- Event handlers ---

    async def on_trigger_fired(self, event_data: dict[str, Any]) -> None:
        """Handle github.TriggerFired — correlate repository to execution."""
        repository = event_data.get("repository", "")
        execution_id = event_data.get("execution_id", "")
        workflow_id = event_data.get("workflow_id", "")

        if not repository or not execution_id:
            logger.debug("TriggerFired missing repository or execution_id, skipping correlation")
            return

        correlation = RepoExecutionCorrelation(
            repo_full_name=repository,
            repo_id=None,
            execution_id=execution_id,
            workflow_id=workflow_id,
            correlation_source="trigger",
            correlated_at=datetime.now(UTC).isoformat(),
        )
        await self._save_correlation(correlation)

    async def on_workflow_execution_started(self, event_data: dict[str, Any]) -> None:
        """Handle WorkflowExecutionStarted — correlate from template inputs."""
        execution_id = event_data.get("execution_id", "")
        workflow_id = event_data.get("workflow_id", "")
        inputs = event_data.get("inputs", {})

        repository_url = inputs.get("repository_url", "") or inputs.get("repository", "")
        if not repository_url or not execution_id:
            return

        # Extract "owner/repo" from various URL formats
        repo_full_name = _extract_repo_name(repository_url)
        if not repo_full_name:
            return

        # Check if correlation already exists (from TriggerFired)
        key = f"{execution_id}:{repo_full_name}"
        existing = await self._store.get(self.PROJECTION_NAME, key)
        if existing:
            return

        correlation = RepoExecutionCorrelation(
            repo_full_name=repo_full_name,
            repo_id=None,
            execution_id=execution_id,
            workflow_id=workflow_id,
            correlation_source="template",
            correlated_at=datetime.now(UTC).isoformat(),
        )
        await self._save_correlation(correlation)

    # --- Query methods ---

    async def get_repos_for_execution(self, execution_id: str) -> list[RepoExecutionCorrelation]:
        """Get all repos correlated with an execution."""
        all_records = await self._store.get_all(self.PROJECTION_NAME)
        return [
            RepoExecutionCorrelation.from_dict(r)
            for r in all_records
            if r.get("execution_id") == execution_id
        ]

    async def get_executions_for_repo(self, repo_full_name: str) -> list[RepoExecutionCorrelation]:
        """Get all executions correlated with a repo."""
        all_records = await self._store.get_all(self.PROJECTION_NAME)
        return [
            RepoExecutionCorrelation.from_dict(r)
            for r in all_records
            if r.get("repo_full_name") == repo_full_name
        ]


def _extract_repo_name(url_or_name: str) -> str:
    """Extract 'owner/repo' from a URL or full name.

    Handles:
    - "owner/repo" (passthrough)
    - "https://github.com/owner/repo"
    - "https://github.com/owner/repo.git"
    - "git@github.com:owner/repo.git"
    """
    if not url_or_name:
        return ""

    # Already in "owner/repo" format
    if "/" in url_or_name and ":" not in url_or_name and "//" not in url_or_name:
        return url_or_name.removesuffix(".git")

    # HTTPS URL
    if "://" in url_or_name:
        parts = url_or_name.rstrip("/").split("/")
        if len(parts) >= 2:
            repo = parts[-1].removesuffix(".git")
            owner = parts[-2]
            return f"{owner}/{repo}"

    # SSH URL (git@github.com:owner/repo.git)
    if ":" in url_or_name:
        path = url_or_name.split(":")[-1]
        return path.removesuffix(".git")

    return ""
