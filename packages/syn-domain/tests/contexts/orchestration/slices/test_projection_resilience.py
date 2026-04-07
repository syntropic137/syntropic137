"""Tests for projection resilience to orphaned failure events (#598).

Verifies that on_workflow_failed creates a minimal entry when no prior
WorkflowExecutionStarted event was processed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syn_domain.contexts.orchestration.slices.get_execution_detail.projection import (
    WorkflowExecutionDetailProjection,
)
from syn_domain.contexts.orchestration.slices.list_executions.projection import (
    WorkflowExecutionListProjection,
)


def _make_store() -> MagicMock:
    """Create a mock projection store."""
    store = MagicMock()
    store.get = AsyncMock(return_value=None)  # No existing entry
    store.save = AsyncMock()
    return store


def _failure_event(execution_id: str = "exec-abc123") -> dict:
    return {
        "execution_id": execution_id,
        "workflow_id": "wf-1",
        "workflow_name": "Test Workflow",
        "failed_at": "2026-04-06T12:00:00Z",
        "error_message": "GitHub App not installed on repository: owner/repo",
        "total_phases": 3,
    }


# -- List projection ----------------------------------------------------------


@pytest.mark.asyncio
async def test_list_projection_creates_entry_on_orphaned_failure() -> None:
    """on_workflow_failed creates a minimal summary when no started event preceded it."""
    store = _make_store()
    projection = WorkflowExecutionListProjection(store)

    await projection.on_workflow_failed(_failure_event())

    store.save.assert_called_once()
    _, exec_id, data = store.save.call_args.args
    assert exec_id == "exec-abc123"
    assert data["status"] == "failed"
    assert data["workflow_id"] == "wf-1"
    assert "GitHub App not installed" in data["error_message"]
    assert data["completed_phases"] == 0
    assert data["total_tokens"] == 0


@pytest.mark.asyncio
async def test_list_projection_updates_existing_on_failure() -> None:
    """on_workflow_failed updates existing entry normally."""
    store = _make_store()
    store.get = AsyncMock(
        return_value={
            "workflow_execution_id": "exec-abc123",
            "workflow_id": "wf-1",
            "status": "running",
            "completed_phases": 1,
        }
    )
    projection = WorkflowExecutionListProjection(store)

    await projection.on_workflow_failed(_failure_event())

    store.save.assert_called_once()
    _, _, data = store.save.call_args.args
    assert data["status"] == "failed"
    assert data["completed_phases"] == 1  # Preserved from existing


# -- Detail projection ---------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_projection_creates_entry_on_orphaned_failure() -> None:
    """on_workflow_failed creates a minimal detail when no started event preceded it."""
    store = _make_store()
    projection = WorkflowExecutionDetailProjection(store)

    await projection.on_workflow_failed(_failure_event())

    store.save.assert_called_once()
    _, exec_id, data = store.save.call_args.args
    assert exec_id == "exec-abc123"
    assert data["status"] == "failed"
    assert data["workflow_id"] == "wf-1"
    assert "GitHub App not installed" in data["error_message"]
    assert data["phases"] == []
    assert data["total_input_tokens"] == 0


@pytest.mark.asyncio
async def test_detail_projection_updates_existing_on_failure() -> None:
    """on_workflow_failed updates existing entry and marks failed phase."""
    store = _make_store()
    store.get = AsyncMock(
        return_value={
            "execution_id": "exec-abc123",
            "workflow_id": "wf-1",
            "status": "running",
            "phases": [{"phase_id": "phase-1", "status": "running"}],
            "error_message": None,
        }
    )
    projection = WorkflowExecutionDetailProjection(store)

    event = _failure_event()
    event["failed_phase_id"] = "phase-1"
    await projection.on_workflow_failed(event)

    store.save.assert_called_once()
    _, _, data = store.save.call_args.args
    assert data["status"] == "failed"
    assert data["phases"][0]["status"] == "failed"
