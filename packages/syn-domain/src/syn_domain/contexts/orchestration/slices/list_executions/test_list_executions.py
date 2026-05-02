"""Tests for workflow execution list projection."""

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest


@pytest.mark.unit
class TestWorkflowExecutionListProjection:
    """Tests for WorkflowExecutionListProjection."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        """Create a mock projection store."""
        store = AsyncMock()
        store.get = AsyncMock(return_value=None)
        store.save = AsyncMock()
        store.get_all = AsyncMock(return_value={})
        return store

    @pytest.mark.asyncio
    async def test_handles_workflow_execution_started(self, mock_store: AsyncMock) -> None:
        """Test that projection creates execution on WorkflowExecutionStarted."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_execution_started(
            {
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "started_at": "2024-12-04T10:00:00Z",
                "total_phases": 3,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]

        assert saved_data["workflow_execution_id"] == "exec-1"
        assert saved_data["workflow_id"] == "workflow-1"
        assert saved_data["workflow_name"] == "Test Workflow"
        assert saved_data["status"] == "running"
        assert saved_data["total_phases"] == 3
        assert saved_data["completed_phases"] == 0
        assert saved_data["total_tokens"] == 0

    @pytest.mark.asyncio
    async def test_handles_phase_completed(self, mock_store: AsyncMock) -> None:
        """Test that projection updates metrics on PhaseCompleted."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        # Setup existing execution
        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "status": "running",
                "completed_phases": 0,
                "total_phases": 3,
                "total_tokens": 0,
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        # Cost is Lane 2 (#695) — projection ignores cost_usd on event
        await projection.on_phase_completed(
            {
                "execution_id": "exec-1",
                "phase_id": "research",
                "total_tokens": 1500,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]

        assert saved_data["completed_phases"] == 1
        assert saved_data["total_tokens"] == 1500
        # Cost is Lane 2 (#695) — projection no longer stores total_cost_usd
        assert "total_cost_usd" not in saved_data

    @pytest.mark.asyncio
    async def test_handles_workflow_completed(self, mock_store: AsyncMock) -> None:
        """Test that projection marks execution completed."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "status": "running",
                "completed_phases": 2,
                "total_phases": 3,
                "total_tokens": 3000,
                "total_cost_usd": "0.20",
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_completed(
            {
                "execution_id": "exec-1",
                "completed_at": "2024-12-04T10:30:00Z",
                "completed_phases": 3,
                "total_tokens": 4500,
                "total_cost_usd": Decimal("0.30"),
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]

        assert saved_data["status"] == "completed"
        assert saved_data["completed_at"] == "2024-12-04T10:30:00Z"
        assert saved_data["completed_phases"] == 3
        assert saved_data["total_tokens"] == 4500

    @pytest.mark.asyncio
    async def test_handles_workflow_failed(self, mock_store: AsyncMock) -> None:
        """Test that projection marks execution failed."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "workflow-1",
                "workflow_name": "Test Workflow",
                "status": "running",
                "completed_phases": 1,
                "total_phases": 3,
            }
        )

        projection = WorkflowExecutionListProjection(mock_store)

        await projection.on_workflow_failed(
            {
                "execution_id": "exec-1",
                "failed_at": "2024-12-04T10:15:00Z",
                "error_message": "Agent timeout",
                "completed_phases": 1,
            }
        )

        mock_store.save.assert_called_once()
        saved_data = mock_store.save.call_args[0][2]

        assert saved_data["status"] == "failed"
        assert saved_data["completed_at"] == "2024-12-04T10:15:00Z"
        assert saved_data["error_message"] == "Agent timeout"

    @pytest.mark.asyncio
    async def test_get_by_workflow_id(self, mock_store: AsyncMock) -> None:
        """Test that get_by_workflow_id filters and sorts executions."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get_all = AsyncMock(
            return_value=[
                {
                    "execution_id": "exec-1",
                    "workflow_id": "workflow-1",
                    "workflow_name": "Test Workflow",
                    "status": "completed",
                    "started_at": "2024-12-04T09:00:00Z",
                    "completed_at": "2024-12-04T09:30:00Z",
                    "completed_phases": 3,
                    "total_phases": 3,
                    "total_tokens": 3000,
                    "total_cost_usd": "0.20",
                },
                {
                    "execution_id": "exec-2",
                    "workflow_id": "workflow-1",
                    "workflow_name": "Test Workflow",
                    "status": "completed",
                    "started_at": "2024-12-04T10:00:00Z",
                    "completed_at": "2024-12-04T10:30:00Z",
                    "completed_phases": 3,
                    "total_phases": 3,
                    "total_tokens": 4000,
                    "total_cost_usd": "0.25",
                },
                {
                    "execution_id": "exec-3",
                    "workflow_id": "workflow-2",  # Different workflow
                    "workflow_name": "Other Workflow",
                    "status": "completed",
                    "started_at": "2024-12-04T11:00:00Z",
                    "completed_phases": 2,
                    "total_phases": 2,
                    "total_tokens": 2000,
                    "total_cost_usd": "0.15",
                },
            ]
        )

        projection = WorkflowExecutionListProjection(mock_store)
        executions = await projection.get_by_workflow_id("workflow-1")

        # Should only return workflow-1 executions
        assert len(executions) == 2
        assert all(e.workflow_id == "workflow-1" for e in executions)

        # Should be sorted by started_at descending (most recent first)
        assert executions[0].workflow_execution_id == "exec-2"
        assert executions[1].workflow_execution_id == "exec-1"


@pytest.mark.unit
class TestWorkflowInterruptedProjection:
    """T-3: Tests for on_workflow_interrupted handler in list_executions projection."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_sets_interrupted_status(self, mock_store: AsyncMock) -> None:
        """WorkflowInterrupted event sets status to 'interrupted'."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "workflow_execution_id": "exec-1",
                "workflow_id": "wf-1",
                "status": "running",
                "completed_phases": 0,
                "total_phases": 2,
                "total_tokens": 50,
                "total_cost_usd": "0",
            }
        )
        mock_store.save = AsyncMock()

        projection = WorkflowExecutionListProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "git_sha": "abc123",
                "reason": "User stopped",
            }
        )

        mock_store.save.assert_called_once()
        saved = mock_store.save.call_args[0][2]
        assert saved["status"] == "interrupted"
        assert saved["completed_at"] == "2026-02-20T10:00:00Z"
        assert saved["error_message"] == "User stopped"

    @pytest.mark.asyncio
    async def test_missing_execution_is_noop(self, mock_store: AsyncMock) -> None:
        """Graceful no-op when execution_id not found in projection store."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(return_value=None)
        mock_store.save = AsyncMock()

        projection = WorkflowExecutionListProjection(mock_store)
        # Should not raise
        await projection.on_workflow_interrupted(
            {
                "execution_id": "nonexistent",
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": "User stopped",
            }
        )

        mock_store.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_reason_uses_default_message(self, mock_store: AsyncMock) -> None:
        """When reason is None, a default error_message is used."""
        from syn_domain.contexts.orchestration.slices.list_executions.projection import (
            WorkflowExecutionListProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "workflow_execution_id": "exec-1",
                "workflow_id": "wf-1",
                "status": "running",
                "total_tokens": 0,
                "total_cost_usd": "0",
            }
        )
        mock_store.save = AsyncMock()

        projection = WorkflowExecutionListProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": None,
            }
        )

        saved = mock_store.save.call_args[0][2]
        assert saved["error_message"] == "Interrupted by user"
