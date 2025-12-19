"""Tests for StaleExecutionCleaner service.

This module tests the background cleanup job that identifies and marks
stale workflow executions as failed.

Test Categories:
- Detection: Finding stale executions
- Threshold: Respecting time thresholds and expected completion
- Cleanup: Marking executions as failed
- Edge cases: Empty results, already completed, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from aef_domain.contexts.workflows.cleanup.stale_execution_cleaner import (
    ExecutionProjectionProtocol,
    ExecutionRepositoryProtocol,
    StaleExecutionCleaner,
)
from aef_domain.contexts.workflows.domain.read_models.workflow_execution_summary import (
    WorkflowExecutionSummary,
)


@dataclass
class MockExecutionSummary:
    """Mock execution summary for testing."""

    workflow_execution_id: str
    workflow_id: str = "workflow-1"
    status: str = "running"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expected_completion_at: datetime | str | None = None

    def to_summary(self) -> WorkflowExecutionSummary:
        """Convert to WorkflowExecutionSummary."""
        return WorkflowExecutionSummary(
            workflow_execution_id=self.workflow_execution_id,
            workflow_id=self.workflow_id,
            workflow_name="Test Workflow",
            status=self.status,
            started_at=self.started_at,
            completed_at=None,
            total_phases=1,
            completed_phases=0,
            total_tokens=0,
            total_cost_usd=Decimal("0"),
            expected_completion_at=self.expected_completion_at,
        )


class MockProjection:
    """Mock projection for testing."""

    def __init__(self, executions: list[MockExecutionSummary] | None = None):
        self.executions = executions or []

    async def get_executions_by_status(
        self,
        status: str,
        started_before: datetime | None = None,
    ) -> list[WorkflowExecutionSummary]:
        """Return mock executions filtered by status and time."""
        results = []
        for ex in self.executions:
            if ex.status != status:
                continue
            if started_before and ex.started_at >= started_before:
                continue
            results.append(ex.to_summary())
        return results


class MockAggregate:
    """Mock execution aggregate for testing."""

    def __init__(self, execution_id: str, status: str = "running"):
        self.execution_id = execution_id
        self._completed_phases = 0
        self._total_phases = 1
        self.commands: list = []

        # Import and set status
        from aef_domain.contexts.workflows._shared.execution_value_objects import (
            ExecutionStatus,
        )

        self.status = ExecutionStatus(status)

    def _handle_command(self, command) -> None:
        """Record commands for verification."""
        self.commands.append(command)
        # Update status to failed
        from aef_domain.contexts.workflows._shared.execution_value_objects import (
            ExecutionStatus,
        )

        self.status = ExecutionStatus.FAILED


class MockRepository:
    """Mock execution repository for testing."""

    def __init__(self):
        self.aggregates: dict[str, MockAggregate] = {}
        self.saved: list[MockAggregate] = []

    def add_aggregate(self, aggregate: MockAggregate) -> None:
        """Add an aggregate to the mock store."""
        self.aggregates[aggregate.execution_id] = aggregate

    async def get(self, execution_id: str) -> MockAggregate | None:
        """Get an aggregate by ID."""
        return self.aggregates.get(execution_id)

    async def save(self, aggregate: MockAggregate) -> None:
        """Save an aggregate (record for verification)."""
        self.saved.append(aggregate)


# Verify protocols are compatible
def _verify_protocols() -> None:
    """Type check that mocks implement protocols."""
    _: ExecutionProjectionProtocol = MockProjection()
    _: ExecutionRepositoryProtocol = MockRepository()


@pytest.mark.unit
class TestStaleExecutionCleaner:
    """Tests for StaleExecutionCleaner service."""

    @pytest.fixture
    def cleaner_with_stale(self):
        """Create a cleaner with stale executions."""
        # Create execution that's 3 hours old (past default 2h threshold)
        stale_time = datetime.now(UTC) - timedelta(hours=3)
        executions = [
            MockExecutionSummary(
                workflow_execution_id="stale-1",
                started_at=stale_time,
            ),
            MockExecutionSummary(
                workflow_execution_id="stale-2",
                started_at=stale_time - timedelta(minutes=30),
            ),
        ]
        projection = MockProjection(executions)
        repo = MockRepository()

        # Add aggregates
        for ex in executions:
            repo.add_aggregate(MockAggregate(ex.workflow_execution_id))

        return StaleExecutionCleaner(projection, repo), projection, repo

    @pytest.fixture
    def cleaner_empty(self):
        """Create a cleaner with no executions."""
        projection = MockProjection([])
        repo = MockRepository()
        return StaleExecutionCleaner(projection, repo), projection, repo

    @pytest.mark.asyncio
    async def test_cleanup_finds_stale_executions(self, cleaner_with_stale):
        """Should find executions running longer than threshold."""
        cleaner, _projection, _repo = cleaner_with_stale

        # Run cleanup with dry_run to just detect
        stale_ids = await cleaner.cleanup_stale_executions(dry_run=True)

        assert len(stale_ids) == 2
        assert "stale-1" in stale_ids
        assert "stale-2" in stale_ids

    @pytest.mark.asyncio
    async def test_cleanup_respects_expected_completion(self):
        """Should skip executions not past expected_completion_at."""
        # Create execution that's old but has future expected completion
        future_completion = datetime.now(UTC) + timedelta(hours=1)
        old_start = datetime.now(UTC) - timedelta(hours=5)

        executions = [
            MockExecutionSummary(
                workflow_execution_id="has-future-expected",
                started_at=old_start,
                expected_completion_at=future_completion,
            ),
            MockExecutionSummary(
                workflow_execution_id="past-expected",
                started_at=old_start,
                expected_completion_at=datetime.now(UTC) - timedelta(minutes=30),
            ),
        ]

        projection = MockProjection(executions)
        repo = MockRepository()

        for ex in executions:
            repo.add_aggregate(MockAggregate(ex.workflow_execution_id))

        cleaner = StaleExecutionCleaner(projection, repo)

        stale_ids = await cleaner.cleanup_stale_executions(dry_run=True)

        # Should only find the one past expected completion
        assert len(stale_ids) == 1
        assert "past-expected" in stale_ids
        assert "has-future-expected" not in stale_ids

    @pytest.mark.asyncio
    async def test_cleanup_dry_run_mode(self, cleaner_with_stale):
        """Dry run should not modify executions."""
        cleaner, _projection, repo = cleaner_with_stale

        stale_ids = await cleaner.cleanup_stale_executions(dry_run=True)

        assert len(stale_ids) == 2
        # Repository should not have any saved aggregates
        assert len(repo.saved) == 0

    @pytest.mark.asyncio
    async def test_cleanup_marks_as_failed(self, cleaner_with_stale):
        """Should emit FailExecutionCommand with stale_timeout reason."""
        cleaner, _projection, repo = cleaner_with_stale

        cleaned_ids = await cleaner.cleanup_stale_executions(dry_run=False)

        assert len(cleaned_ids) == 2

        # Check that aggregates were saved
        assert len(repo.saved) == 2

        # Check that commands were issued
        for aggregate in repo.saved:
            assert len(aggregate.commands) == 1
            cmd = aggregate.commands[0]
            assert cmd.error_type == "stale_timeout"
            assert "timed out" in cmd.error

    @pytest.mark.asyncio
    async def test_get_stale_count(self, cleaner_with_stale):
        """Should return count without modifying anything."""
        cleaner, _projection, repo = cleaner_with_stale

        count = await cleaner.get_stale_count()

        assert count == 2
        # Nothing should be modified
        assert len(repo.saved) == 0

    @pytest.mark.asyncio
    async def test_cleanup_skips_completed_executions(self):
        """Should only clean up executions in RUNNING status."""
        old_time = datetime.now(UTC) - timedelta(hours=5)
        executions = [
            MockExecutionSummary(
                workflow_execution_id="completed-1",
                started_at=old_time,
                status="completed",
            ),
            MockExecutionSummary(
                workflow_execution_id="running-1",
                started_at=old_time,
                status="running",
            ),
        ]

        projection = MockProjection(executions)
        repo = MockRepository()

        # Add aggregates with correct status
        repo.add_aggregate(MockAggregate("completed-1", status="completed"))
        repo.add_aggregate(MockAggregate("running-1", status="running"))

        cleaner = StaleExecutionCleaner(projection, repo)

        # Projection should only return running ones
        stale_ids = await cleaner.cleanup_stale_executions(dry_run=True)

        assert len(stale_ids) == 1
        assert "running-1" in stale_ids

    @pytest.mark.asyncio
    async def test_cleanup_no_stale_executions(self, cleaner_empty):
        """Should handle empty results gracefully."""
        cleaner, _projection, _repo = cleaner_empty

        stale_ids = await cleaner.cleanup_stale_executions()

        assert stale_ids == []

    @pytest.mark.asyncio
    async def test_cleanup_custom_threshold(self):
        """Should respect custom threshold parameter."""
        # Execution 30 minutes old
        recent_time = datetime.now(UTC) - timedelta(minutes=30)
        executions = [
            MockExecutionSummary(
                workflow_execution_id="recent-1",
                started_at=recent_time,
            ),
        ]

        projection = MockProjection(executions)
        repo = MockRepository()
        repo.add_aggregate(MockAggregate("recent-1"))

        cleaner = StaleExecutionCleaner(projection, repo)

        # With default 2h threshold, should find nothing
        stale_default = await cleaner.cleanup_stale_executions(dry_run=True)
        assert len(stale_default) == 0

        # With 15 minute threshold, should find it
        stale_short = await cleaner.cleanup_stale_executions(
            threshold=timedelta(minutes=15),
            dry_run=True,
        )
        assert len(stale_short) == 1
        assert "recent-1" in stale_short

    @pytest.mark.asyncio
    async def test_cleanup_aggregate_not_found(self):
        """Should handle missing aggregates gracefully."""
        old_time = datetime.now(UTC) - timedelta(hours=3)
        executions = [
            MockExecutionSummary(
                workflow_execution_id="missing-1",
                started_at=old_time,
            ),
        ]

        projection = MockProjection(executions)
        repo = MockRepository()  # Empty - no aggregates

        cleaner = StaleExecutionCleaner(projection, repo)

        # Should not crash - ID is still added even if aggregate not found
        # (the _mark_as_failed returns silently)
        cleaned_ids = await cleaner.cleanup_stale_executions()

        # ID is added even though nothing was actually cleaned
        # (this could be improved in the production code)
        assert len(cleaned_ids) == 1

    @pytest.mark.asyncio
    async def test_cleanup_expected_completion_as_string(self):
        """Should handle expected_completion_at as ISO string."""
        old_start = datetime.now(UTC) - timedelta(hours=5)
        past_expected_str = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        executions = [
            MockExecutionSummary(
                workflow_execution_id="string-expected",
                started_at=old_start,
                expected_completion_at=past_expected_str,
            ),
        ]

        projection = MockProjection(executions)
        repo = MockRepository()
        repo.add_aggregate(MockAggregate("string-expected"))

        cleaner = StaleExecutionCleaner(projection, repo)

        stale_ids = await cleaner.cleanup_stale_executions(dry_run=True)

        assert len(stale_ids) == 1
        assert "string-expected" in stale_ids

    @pytest.mark.asyncio
    async def test_cleanup_max_batch_size(self):
        """Should limit cleanup to MAX_BATCH_SIZE executions."""
        old_time = datetime.now(UTC) - timedelta(hours=3)
        # Create more than MAX_BATCH_SIZE (100) executions
        executions = [
            MockExecutionSummary(
                workflow_execution_id=f"stale-{i}",
                started_at=old_time,
            )
            for i in range(150)
        ]

        projection = MockProjection(executions)
        repo = MockRepository()
        for ex in executions:
            repo.add_aggregate(MockAggregate(ex.workflow_execution_id))

        cleaner = StaleExecutionCleaner(projection, repo)

        cleaned_ids = await cleaner.cleanup_stale_executions()

        # Should only clean up MAX_BATCH_SIZE (100)
        assert len(cleaned_ids) == 100
