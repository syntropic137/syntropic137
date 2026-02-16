"""Tests for aef_api.v1.workflows — create, list, get cycle.

Uses APP_ENVIRONMENT=test for in-memory adapters.
"""

import os

import pytest

from aef_api.types import Err, Ok

# Ensure test environment for in-memory adapters
os.environ.setdefault("APP_ENVIRONMENT", "test")


@pytest.fixture(autouse=True)
def _reset_storage():
    """Reset in-memory storage and projections between tests."""
    from aef_adapters.projection_stores import get_projection_store
    from aef_adapters.projections.manager import reset_projection_manager
    from aef_adapters.storage import reset_storage

    reset_storage()
    reset_projection_manager()
    # Reset the projection store data
    store = get_projection_store()
    if hasattr(store, "_data"):
        store._data.clear()
    if hasattr(store, "_state"):
        store._state.clear()
    yield
    reset_storage()
    reset_projection_manager()


async def test_create_workflow():
    """Create a workflow and get back an ID."""
    from aef_api.v1.workflows import create_workflow

    result = await create_workflow(
        name="Test Research Workflow",
        workflow_type="research",
        description="A test workflow",
    )

    assert isinstance(result, Ok)
    assert isinstance(result.value, str)
    assert len(result.value) > 0


async def test_list_workflows_empty():
    """List workflows when none exist."""
    from aef_api.v1.workflows import list_workflows

    result = await list_workflows()

    assert isinstance(result, Ok)
    assert result.value == []


async def test_create_and_list_workflows():
    """Create a workflow then list it."""
    from aef_api.v1.workflows import create_workflow, list_workflows

    create_result = await create_workflow(
        name="Listed Workflow",
        workflow_type="custom",
    )
    assert isinstance(create_result, Ok)

    list_result = await list_workflows()
    assert isinstance(list_result, Ok)
    assert len(list_result.value) == 1
    assert list_result.value[0].name == "Listed Workflow"
    assert list_result.value[0].workflow_type == "custom"


async def test_create_and_get_workflow():
    """Create a workflow then get its details."""
    from aef_api.v1.workflows import create_workflow, get_workflow

    create_result = await create_workflow(
        name="Detail Workflow",
        workflow_type="implementation",
        description="Test getting details",
    )
    assert isinstance(create_result, Ok)
    workflow_id = create_result.value

    get_result = await get_workflow(workflow_id)
    assert isinstance(get_result, Ok)
    assert get_result.value.id == workflow_id
    assert get_result.value.name == "Detail Workflow"


async def test_get_workflow_not_found():
    """Get a workflow that doesn't exist."""
    from aef_api.v1.workflows import get_workflow

    result = await get_workflow("nonexistent-id")
    assert isinstance(result, Err)


async def test_create_workflow_with_phases():
    """Create a workflow with custom phases."""
    from aef_api.v1.workflows import create_workflow

    result = await create_workflow(
        name="Multi-Phase Workflow",
        workflow_type="implementation",
        phases=[
            {"name": "Research", "order": 1, "description": "Research phase"},
            {"name": "Implementation", "order": 2, "description": "Code it"},
            {"name": "Review", "order": 3, "description": "Review code"},
        ],
    )
    assert isinstance(result, Ok)


async def test_list_workflows_with_filter():
    """Create workflows of different types and filter."""
    from aef_api.v1.workflows import create_workflow, list_workflows

    await create_workflow(name="Research 1", workflow_type="research")
    await create_workflow(name="Custom 1", workflow_type="custom")

    result = await list_workflows(workflow_type="research")
    assert isinstance(result, Ok)
    assert len(result.value) == 1
    assert result.value[0].name == "Research 1"


async def test_list_executions_empty():
    """List executions when none exist."""
    from aef_api.v1.workflows import list_executions

    result = await list_executions()
    assert isinstance(result, Ok)
    assert result.value == []
