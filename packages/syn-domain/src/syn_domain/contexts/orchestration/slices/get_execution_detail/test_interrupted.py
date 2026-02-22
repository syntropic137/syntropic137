"""Tests for on_workflow_interrupted handler in get_execution_detail projection."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.unit
class TestWorkflowInterruptedDetailProjection:
    """T-6: Tests for on_workflow_interrupted handler in get_execution_detail projection."""

    @pytest.fixture
    def mock_store(self) -> AsyncMock:
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_sets_interrupted_status(self, mock_store: AsyncMock) -> None:
        """WorkflowInterrupted event sets status to 'interrupted'."""
        from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection as GetExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "workflow_id": "wf-1",
                "status": "running",
                "phases": [{"phase_id": "p-1", "status": "running"}],
            }
        )
        mock_store.save = AsyncMock()

        projection = GetExecutionDetailProjection(mock_store)
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
        assert saved["git_sha"] == "abc123"

    @pytest.mark.asyncio
    async def test_marks_interrupted_phase(self, mock_store: AsyncMock) -> None:
        """The phase matching phase_id is marked as interrupted."""
        from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection as GetExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(
            return_value={
                "execution_id": "exec-1",
                "status": "running",
                "phases": [
                    {"phase_id": "p-1", "status": "completed"},
                    {"phase_id": "p-2", "status": "running"},
                ],
            }
        )
        mock_store.save = AsyncMock()

        projection = GetExecutionDetailProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "execution_id": "exec-1",
                "phase_id": "p-2",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": "User stopped",
            }
        )

        saved = mock_store.save.call_args[0][2]
        phases = {p["phase_id"]: p["status"] for p in saved["phases"]}
        assert phases["p-1"] == "completed"
        assert phases["p-2"] == "interrupted"

    @pytest.mark.asyncio
    async def test_no_reason_uses_default_message(self, mock_store: AsyncMock) -> None:
        """When reason is None, a default error_message is used."""
        from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection as GetExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(
            return_value={"execution_id": "exec-1", "status": "running", "phases": []}
        )
        mock_store.save = AsyncMock()

        projection = GetExecutionDetailProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "execution_id": "exec-1",
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": None,
            }
        )

        saved = mock_store.save.call_args[0][2]
        assert saved["error_message"] == "Interrupted by user"

    @pytest.mark.asyncio
    async def test_missing_execution_is_noop(self, mock_store: AsyncMock) -> None:
        """Graceful no-op when execution not found in projection store."""
        from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection as GetExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(return_value=None)
        mock_store.save = AsyncMock()

        projection = GetExecutionDetailProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "execution_id": "nonexistent",
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": "User stopped",
            }
        )

        mock_store.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_execution_id_is_noop(self, mock_store: AsyncMock) -> None:
        """Graceful no-op when execution_id is absent from event data."""
        from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
            WorkflowExecutionDetailProjection as GetExecutionDetailProjection,
        )

        mock_store.get = AsyncMock(return_value=None)
        mock_store.save = AsyncMock()

        projection = GetExecutionDetailProjection(mock_store)
        await projection.on_workflow_interrupted(
            {
                "phase_id": "p-1",
                "interrupted_at": "2026-02-20T10:00:00Z",
                "reason": "User stopped",
            }
        )

        mock_store.save.assert_not_called()
