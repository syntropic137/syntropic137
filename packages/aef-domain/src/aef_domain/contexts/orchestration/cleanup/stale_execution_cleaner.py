"""Background job to clean up stale executions.

Runs periodically (or on-demand) to:
1. Find executions stuck in "running" status past their expected completion
2. Mark them as "failed" with reason "stale_timeout"
3. Emit WorkflowFailed event for proper cleanup

Usage:
    cleaner = StaleExecutionCleaner(projection, execution_repo)

    # Manual cleanup (e.g., from CLI or API endpoint)
    cleaned_ids = await cleaner.cleanup_stale_executions()

    # Or with custom threshold
    cleaned_ids = await cleaner.cleanup_stale_executions(threshold=timedelta(hours=4))
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
        WorkflowExecutionAggregate,
    )
    from aef_domain.contexts.orchestration.domain.read_models.workflow_execution_summary import (
        WorkflowExecutionSummary,
    )

logger = logging.getLogger(__name__)


class ExecutionProjectionProtocol(Protocol):
    """Protocol for querying execution projections."""

    async def get_executions_by_status(
        self,
        status: str,
        started_before: datetime | None = None,
    ) -> list[WorkflowExecutionSummary]:
        """Get executions filtered by status and optionally by start time."""
        ...


class ExecutionRepositoryProtocol(Protocol):
    """Protocol for the execution repository."""

    async def get(self, execution_id: str) -> WorkflowExecutionAggregate | None:
        """Get an execution aggregate by ID."""
        ...

    async def save(self, aggregate: WorkflowExecutionAggregate) -> None:
        """Save an execution aggregate."""
        ...


class StaleExecutionCleaner:
    """Cleans up workflow executions stuck in "running" status.

    This service identifies executions that have been running for too long
    and marks them as failed. This can happen when:
    - Container crashes without emitting a final event
    - Network issues prevent event delivery
    - Agent hangs without timeout enforcement
    - System restart loses in-flight executions
    """

    # Default threshold: 2 hours
    DEFAULT_STALE_THRESHOLD = timedelta(hours=2)

    # Maximum batch size for cleanup
    MAX_BATCH_SIZE = 100

    def __init__(
        self,
        projection: ExecutionProjectionProtocol,
        execution_repository: ExecutionRepositoryProtocol,
    ):
        """Initialize the cleaner.

        Args:
            projection: Projection for querying execution summaries
            execution_repository: Repository for loading/saving aggregates
        """
        self._projection = projection
        self._executions = execution_repository

    async def cleanup_stale_executions(
        self,
        threshold: timedelta | None = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Find and mark stale executions as failed.

        Args:
            threshold: How long an execution can run before being considered stale.
                       Defaults to 2 hours.
            dry_run: If True, don't actually update executions, just return IDs.

        Returns:
            List of execution IDs that were (or would be) cleaned up.
        """
        threshold = threshold or self.DEFAULT_STALE_THRESHOLD
        cutoff = datetime.now(UTC) - threshold

        logger.info(
            "Looking for stale executions (running since before %s)",
            cutoff.isoformat(),
        )

        # Find running executions that started before the cutoff
        stale_executions = await self._projection.get_executions_by_status(
            status="running",
            started_before=cutoff,
        )

        if not stale_executions:
            logger.info("No stale executions found")
            return []

        logger.info(
            "Found %d stale executions to clean up",
            len(stale_executions),
        )

        cleaned: list[str] = []

        for summary in stale_executions[: self.MAX_BATCH_SIZE]:
            execution_id = summary.workflow_execution_id

            # Also check expected_completion_at if set
            if summary.expected_completion_at:
                expected_raw = summary.expected_completion_at
                expected_dt: datetime | None = None
                if isinstance(expected_raw, str):
                    try:
                        expected_dt = datetime.fromisoformat(expected_raw.replace("Z", "+00:00"))
                    except ValueError:
                        expected_dt = None
                elif isinstance(expected_raw, datetime):
                    expected_dt = expected_raw

                if expected_dt and expected_dt > datetime.now(UTC):
                    # Not yet past expected completion - skip
                    logger.debug(
                        "Skipping %s - not past expected completion",
                        execution_id,
                    )
                    continue

            if dry_run:
                logger.info("[DRY RUN] Would clean up: %s", execution_id)
                cleaned.append(execution_id)
                continue

            try:
                await self._mark_as_failed(
                    execution_id=execution_id,
                    reason="stale_timeout",
                    message=f"Execution timed out after {threshold}",
                )
                cleaned.append(execution_id)
                logger.info("Cleaned up stale execution: %s", execution_id)
            except Exception:
                logger.exception(
                    "Failed to clean up execution %s",
                    execution_id,
                )

        if dry_run:
            logger.info("[DRY RUN] Would have cleaned up %d executions", len(cleaned))
        else:
            logger.info("Cleaned up %d stale executions", len(cleaned))

        return cleaned

    async def _mark_as_failed(
        self,
        execution_id: str,
        reason: str,
        message: str,
    ) -> None:
        """Mark an execution as failed.

        Loads the aggregate, emits FailExecution command, and saves.
        """
        from aef_domain.contexts.orchestration.domain.aggregate_execution.WorkflowExecutionAggregate import (
            FailExecutionCommand,
        )

        aggregate = await self._executions.get(execution_id)
        if aggregate is None:
            logger.warning("Execution not found: %s", execution_id)
            return

        # Only fail if still running
        from aef_domain.contexts.orchestration.domain.aggregate_execution.value_objects import (
            ExecutionStatus,
        )

        if aggregate.status != ExecutionStatus.RUNNING:
            logger.debug(
                "Execution %s is not running (status: %s), skipping",
                execution_id,
                aggregate.status,
            )
            return

        # Get current state
        completed_phases = (
            aggregate._completed_phases if hasattr(aggregate, "_completed_phases") else 0
        )
        total_phases = aggregate._total_phases if hasattr(aggregate, "_total_phases") else 0

        fail_cmd = FailExecutionCommand(
            execution_id=execution_id,
            error=message,
            error_type=reason,
            failed_phase_id=None,  # Unknown which phase was running
            completed_phases=completed_phases,
            total_phases=total_phases,
        )
        aggregate._handle_command(fail_cmd)
        await self._executions.save(aggregate)

    async def get_stale_count(
        self,
        threshold: timedelta | None = None,
    ) -> int:
        """Get count of stale executions without cleaning them.

        Useful for monitoring/alerting.
        """
        threshold = threshold or self.DEFAULT_STALE_THRESHOLD
        cutoff = datetime.now(UTC) - threshold

        stale = await self._projection.get_executions_by_status(
            status="running",
            started_before=cutoff,
        )
        return len(stale)
