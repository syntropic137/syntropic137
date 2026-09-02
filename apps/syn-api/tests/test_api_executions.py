"""Tests for syn_api.routes.executions — list, get, get_detail, list_active."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest

from syn_api.types import Err, Ok

# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from syn_adapters.projection_stores import get_projection_store
    from syn_adapters.projections.manager import reset_projection_manager
    from syn_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def _seed_execution(
    exec_id: str,
    workflow_id: str,
    workflow_name: str,
    status: str = "running",
    total_phases: int = 2,
) -> None:
    """Seed an execution into both projection stores."""
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()

    # Seed into execution list projection
    await manager.workflow_execution_list._store.save(
        "workflow_executions",
        exec_id,
        {
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": status,
            "started_at": "2026-03-23T10:00:00Z",
            "completed_at": None if status == "running" else "2026-03-23T10:05:00Z",
            "completed_phases": 0 if status == "running" else total_phases,
            "total_phases": total_phases,
            "total_tokens": 1000,
            "total_cost_usd": "0.05",
            "tool_call_count": 5,
            "error_message": None,
        },
    )

    # Seed into execution detail projection
    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "status": status,
            "started_at": "2026-03-23T10:00:00Z",
            "completed_at": None if status == "running" else "2026-03-23T10:05:00Z",
            "total_input_tokens": 500,
            "total_output_tokens": 500,
            "total_cost_usd": "0.05",
            "total_duration_seconds": 30.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [],
        },
    )


async def test_list_executions_with_data():
    """Seed two executions, verify list_ returns both."""
    from syn_api.routes.executions import list_

    await _seed_execution("exec-1", "wf-1", "Workflow A")
    await _seed_execution("exec-2", "wf-1", "Workflow A", status="completed")

    result = await list_()
    assert isinstance(result, Ok)
    assert len(result.value) == 2
    ids = {e.workflow_execution_id for e in result.value}
    assert ids == {"exec-1", "exec-2"}


async def test_list_executions_filter_by_workflow():
    """Seed executions for two workflows, filter by one."""
    from syn_api.routes.executions import list_

    await _seed_execution("exec-a", "wf-1", "Workflow A")
    await _seed_execution("exec-b", "wf-2", "Workflow B")
    await _seed_execution("exec-c", "wf-1", "Workflow A", status="completed")

    result = await list_(workflow_id="wf-1")
    assert isinstance(result, Ok)
    assert len(result.value) == 2
    assert all(e.workflow_id == "wf-1" for e in result.value)


async def test_get_execution():
    """Seed an execution, get by ID."""
    from syn_api.routes.executions import get

    await _seed_execution("exec-get-1", "wf-1", "Workflow A")

    result = await get("exec-get-1")
    assert isinstance(result, Ok)
    assert result.value.workflow_execution_id == "exec-get-1"
    assert result.value.workflow_id == "wf-1"
    assert result.value.workflow_name == "Workflow A"
    assert result.value.total_input_tokens == 500
    assert result.value.total_output_tokens == 500


async def test_get_execution_not_found():
    """Get nonexistent execution returns Err."""
    from syn_api.routes.executions import get

    result = await get("nonexistent-id")
    assert isinstance(result, Err)


async def test_get_detail():
    """Seed an execution, get full detail."""
    from syn_api.routes.executions import get_detail

    await _seed_execution("exec-detail-1", "wf-1", "Workflow A")

    result = await get_detail("exec-detail-1")
    assert isinstance(result, Ok)
    assert result.value.workflow_execution_id == "exec-detail-1"
    assert result.value.workflow_id == "wf-1"
    assert result.value.phases == []


async def test_get_detail_not_found():
    """Get detail for nonexistent execution returns Err."""
    from syn_api.routes.executions import get_detail

    result = await get_detail("nonexistent-id")
    assert isinstance(result, Err)


async def _seed_execution_with_running_phase(
    exec_id: str, workflow_id: str, phase_started_at: str
) -> None:
    """Seed an execution with a single RUNNING phase, exactly as the
    projection would leave it mid-flight: duration_seconds still 0.0
    (nothing has completed it yet) and no completed_at.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr

    await ensure_connected()
    manager = get_projection_mgr()

    await manager.workflow_execution_detail._store.save(
        "workflow_execution_details",
        exec_id,
        {
            "execution_id": exec_id,
            "workflow_execution_id": exec_id,
            "workflow_id": workflow_id,
            "workflow_name": "Workflow A",
            "status": "running",
            "started_at": phase_started_at,
            "completed_at": None,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost_usd": "0",
            "total_duration_seconds": 0.0,
            "artifact_ids": [],
            "error_message": None,
            "phases": [
                {
                    "workflow_phase_id": "phase-1",
                    "name": "Phase 1",
                    "status": "running",
                    "session_id": None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 0,
                    "duration_seconds": 0.0,
                    "started_at": phase_started_at,
                    "completed_at": None,
                    "error_message": None,
                }
            ],
        },
    )


async def test_get_detail_running_phase_duration_advances_between_reads():
    """A RUNNING phase's duration_seconds must be computed live, not read
    back as the 0.0 the projection seeded it with.

    Regression test for the 2026-09-01 incident: six healthy workflow runs
    were cancelled because a running phase's duration looked frozen. A test
    that only asserted ``duration_seconds is not None`` would already pass
    today against the stored ``0.0`` -- so this asserts the value ADVANCES
    between two reads of the same still-running phase, which is only
    possible if it is computed against the wall clock at read time.
    """
    from syn_api.routes.executions import get_detail

    started_at = (datetime.now(UTC) - timedelta(seconds=100)).isoformat()
    await _seed_execution_with_running_phase("exec-running-phase", "wf-1", started_at)

    first = await get_detail("exec-running-phase")
    assert isinstance(first, Ok)
    first_duration = first.value.phases[0].duration_seconds
    assert first_duration is not None
    assert first_duration > 0.0

    await asyncio.sleep(0.05)

    second = await get_detail("exec-running-phase")
    assert isinstance(second, Ok)
    second_duration = second.value.phases[0].duration_seconds
    assert second_duration is not None
    assert second_duration > first_duration


async def test_list_active():
    """Seed running + completed executions, list_active returns only running."""
    from syn_api.routes.executions import list_active

    await _seed_execution("exec-running", "wf-1", "Workflow A", status="running")
    await _seed_execution("exec-done", "wf-1", "Workflow A", status="completed")
    await _seed_execution("exec-failed", "wf-2", "Workflow B", status="failed")

    result = await list_active()
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].workflow_execution_id == "exec-running"
    assert result.value[0].status == "running"
