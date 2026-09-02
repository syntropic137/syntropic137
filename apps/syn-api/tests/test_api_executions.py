"""Tests for syn_api.routes.executions — list, get, get_detail, list_active."""

import os

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


async def test_task_reaches_execution_endpoints():
    """`task` must reach both GET /executions and GET /executions/{id} HTTP
    responses (#1075), not just the domain summary/detail objects.

    A fixture value that arose without the fix (e.g. task=None matching the
    default) proves nothing, so this seeds a real task string that could only
    appear here via the read path this issue is about, then asserts it
    survives all the way into the Pydantic response models FastAPI actually
    serializes -- the constructor hop a summary-only check would miss.
    """
    from syn_api._wiring import ensure_connected, get_projection_mgr
    from syn_api.routes.executions.queries import (
        _build_execution_summary_response,
        get_execution_endpoint,
        list_,
    )

    task_text = "Fix issue #1075 in the syntropic137 repo"
    await _seed_execution("exec-task-api", "wf-1", "Workflow A")

    await ensure_connected()
    manager = get_projection_mgr()
    for projection_name, key in (
        ("workflow_executions", "exec-task-api"),
        ("workflow_execution_details", "exec-task-api"),
    ):
        data = await manager.store.get(projection_name, key)
        data["task"] = task_text
        await manager.store.save(projection_name, key, data)

    # List endpoint path: domain summary -> ExecutionSummary -> HTTP response.
    list_result = await list_()
    assert isinstance(list_result, Ok)
    summary = next(e for e in list_result.value if e.workflow_execution_id == "exec-task-api")
    assert summary.task == task_text
    response = _build_execution_summary_response(summary)
    assert response.task == task_text

    # Detail endpoint path: domain detail -> get_detail -> HTTP response model
    # actually returned by GET /api/v1/executions/{id}. exec-task-api is an
    # exact key in the store so resolve_or_raise's fast path applies -- no
    # need to fake prefix resolution.
    detail_response = await get_execution_endpoint("exec-task-api")
    assert detail_response.task == task_text
